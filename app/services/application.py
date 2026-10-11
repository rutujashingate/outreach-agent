"""The one application boundary used by Telegram and the dashboard.

Submitting work saves a job immediately. execute_one is the only queue worker;
model/tool calls never run inside a Telegram message handler or web request.
"""
import asyncio
from uuid import uuid4

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.domain.workflow import ApprovalDecision, ApprovalSubmission, WorkflowRequest, WorkflowState
from app.agent.nodes.approval import validate_decisions
from app.llm.client import ModelProviderError
from app.services.limits import LimitExceeded
from app.services.runs import RunConflict, RunNotFound
from app.storage.control import ControlStore, JobRow, RunMeta, now
from app.storage.models import RunRow, TraceRow, ActionRow
from app.storage.events import trace


class AgentService:
    def __init__(self, manager):
        self.manager = manager
        self.store = ControlStore(manager.repository.engine)
        from app.services.documents import DocumentService
        self.documents = DocumentService(manager.repository.engine, manager.settings)
        from app.services.conversation import ConversationService
        self.conversations = ConversationService(self)
        self.stopping = asyncio.Event()
        self.worker_busy = False

    def start(self, request: WorkflowRequest, key: str, origin="dashboard"):
        existing = self.store.find_job(key)
        if existing: return existing
        ids = [item.document_id for item in request.attachments]
        if len(ids) != len(set(ids)): raise ValueError('Attach each file only once.')
        for document_id in ids:
            record = self.documents.get(document_id)
            if record['status'] == 'failed': raise RunConflict('An attached file could not be read. Retry it or remove it before starting.')
        gmail = self.manager.gmail
        account = gmail.status() if gmail and hasattr(gmail, "status") else {}
        if account.get("connected") and request.sender.email is None:
            request = request.model_copy(update={"sender": request.sender.model_copy(update={"email": account["email"]})})
        self.manager.validate_request(request)
        if request.gmail_action != "none" and hasattr(gmail, "status"):
            if not account.get("connected"):
                raise RunConflict("Connect Gmail before requesting a draft or send.")
            if (request.sender.email or "").casefold() != account["email"].casefold():
                raise RunConflict("The sender must match the connected Gmail account.")
        state = WorkflowState(run_id=uuid4().hex, **request.model_dump(), gmail_account_id=account.get("account_id"))
        return self.store.enqueue("start", state.run_id, {}, key, state=state, origin=origin)

    def state(self, run_id):
        return self.manager.get(run_id)

    def decisions(self, run_id, submission: ApprovalSubmission, key):
        existing = self.store.find_job(key)
        if existing: return existing
        response = self.state(run_id)
        if not response.awaiting_approval: raise RunConflict("This run is not awaiting approval.")
        validate_decisions(response.state, submission)
        return self.store.enqueue("decisions", run_id, submission.model_dump(mode="json"), key)

    def select_recipients(self, run_id, selections, key):
        from app.agent.nodes.recipients import validate_selections
        existing = self.store.find_job(key)
        if existing: return existing
        response = self.state(run_id)
        if not response.awaiting_recipients: raise RunConflict("This run is not awaiting recipients.")
        validate_selections(response.state, selections)
        return self.store.enqueue("recipients", run_id, selections, key)

    def stage_decision(self, run_id, decision: ApprovalDecision):
        """Save one choice; the final submit still validates the entire batch."""
        response = self.state(run_id)
        if not response.awaiting_approval: raise RunConflict("This approval has already been resolved.")
        expected = {r.prospect.id: r for r in response.state.approval_requests}
        current = expected.get(decision.prospect_id)
        if current is None or (current.version, current.fingerprint) != (decision.version, decision.fingerprint):
            raise RunConflict("This decision refers to an older draft. Review the current version.")
        self.store.put(f"choice:{run_id}:{decision.prospect_id}", decision.model_dump(mode="json"))
        return self.choices(run_id)

    def choices(self, run_id):
        state = self.state(run_id).state
        selections = {}
        for request in state.approval_requests:
            item = self.store.get(f"choice:{run_id}:{request.prospect.id}")
            if item and item["fingerprint"] == request.fingerprint and item["version"] == request.version:
                selections[request.prospect.id] = item
        return selections

    def submit_choices(self, run_id, key):
        existing = self.store.find_job(key)
        if existing: return existing
        return self.decisions(run_id, ApprovalSubmission(decisions=list(self.choices(run_id).values())), key)

    def retry(self, run_id, key):
        existing = self.store.find_job(key)
        if existing: return existing
        row = self.manager.repository.run(run_id)
        if row is None: raise RunNotFound("Unknown run.")
        if row["status"] != "failed": raise RunConflict("Only failed or interrupted runs can be retried.")
        if self.store.cancellation_requested(run_id): raise RunConflict("Cancelled runs cannot be retried.")
        if (self.store.metadata(run_id) or {}).get('kind') == 'chat':
            return self.store.enqueue('chat', run_id, self.conversations.retry_payload(run_id), key)
        return self.store.enqueue("retry", run_id, {}, key)

    def cancel(self, run_id):
        response = self.state(run_id)
        row = self.manager.repository.run(run_id)
        if row["status"] in {"completed", "cancelled"}: raise RunConflict("This run has already ended.")
        self.store.cancel(run_id)
        if row["status"] != "running":
            response.state.current_step = "cancelled"
            self.manager.repository.save_run(response.state, "cancelled")
        trace(self.manager.repository, run_id, "cancel_requested")
        return {"run_id": run_id, "status": "cancel_requested"}

    def queue_replies(self, key):
        gmail = self.manager.gmail
        if gmail is None: raise RunConflict("Connect Gmail first.")
        if hasattr(gmail, "status") and not gmail.status().get("connected"):
            raise RunConflict("Reconnect Gmail before checking replies.")
        return self.store.enqueue("replies", None, {}, key)

    async def check_replies(self):
        from app.connectors.gmail.client import contact_messages
        from app.agent.replies import process_reply
        from app.domain.workflow import ReplyRequest
        from app.storage.repository import stable_id
        gmail, count, seen = self.manager.gmail, 0, set()
        account = gmail.status() if hasattr(gmail, "status") else {}
        cursor_key = 'reply_cursor:' + account.get('account_id', 'local')
        cursor = self.store.get(cursor_key, {}).get('after', '')
        with Session(self.store.engine) as session:
            query = select(ActionRow).where(ActionRow.status == "done", ActionRow.kind.in_(["send", "draft"]))
            rows = list(session.scalars(query.where(ActionRow.key > cursor).order_by(ActionRow.key).limit(20)))
            if not rows and cursor:
                cursor = ''
                rows = list(session.scalars(query.order_by(ActionRow.key).limit(20)))
            tracked = [(r.key, r.email, r.payload.get("outcome", {}).get("thread_id"), r.payload.get("run_id")) for r in rows]
        # Bound reads too: a mailbox with no new replies must not monopolize
        # the worker. A saved cursor rotates through at most 20 tracked actions.
        for action_key, email, thread_id, original_id in tracked:
            previous_cursor, cursor = cursor, action_key
            self.store.put(cursor_key, {'after': cursor})
            if not thread_id or thread_id in seen: continue
            seen.add(thread_id)
            original = self.manager.repository.run(original_id) if original_id else None
            if account and (not original or original["state"].get("gmail_account_id") != account.get("account_id")): continue
            reader = gmail.for_run(account['email'], account['account_id']) if hasattr(gmail, 'for_run') else gmail
            async with asyncio.timeout(self.manager.settings.limits.tool_timeout):
                thread = await reader.read_thread(thread_id)
            for message in contact_messages(thread, email):
                if not message["inbound"]: continue
                key = stable_id(email.casefold(), message["source"], "reply_processing")
                if self.manager.repository.action(key): continue
                await process_reply(self.manager, ReplyRequest(contact_email=email, source=message["source"], body=message["body"]))
                count += 1
                if count == 5:
                    # Revisit this thread next time in case it has more replies.
                    self.store.put(cursor_key, {'after': previous_cursor})
                    return count
        return count

    def current_step(self, run_id, saved_step, status):
        if status == 'running':
            return self.store.get('progress:' + run_id, {}).get('node', saved_step)
        return saved_step

    async def execute_one(self):
        job = self.store.claim()
        if job is None: return False
        self.worker_busy = True
        try:
            run_id, kind = job["run_id"], job["kind"]
            if kind == 'chat':
                status = await self.conversations.execute(job)
                self.store.finish_job(job['id'], status)
                return True
            if kind == "start": result = await self.manager.execute_new(run_id)
            elif kind == "decisions": result = await self.manager.resume(run_id, ApprovalSubmission.model_validate(job["payload"]))
            elif kind == "recipients": result = await self.manager.select_recipients(run_id, job["payload"])
            elif kind == "retry": result = await self.manager.retry(run_id)
            elif kind == 'document':
                document = await self.documents.extract(job['payload']['document_id'])
                result = None
            elif kind == "replies":
                count = await self.check_replies()
                self.store.put("reply_check", {"processed": count, "checked_at": now()})
                result = None
            else: raise ValueError("Unknown job type.")
            status = "cancelled" if result and result.state.current_step == "cancelled" else "completed"
            self.store.finish_job(job["id"], status)
            if kind == 'document':
                message = f"File ready: {document['filename']} ({len(document['content']['pages'])} pages/sections). Ask me a question about it, or inspect the text in the dashboard."
            else: message = (f"Run {run_id}: {result.state.current_step}.\nUse /review {run_id} or open the dashboard."
                       if result else f"Reply check complete: {count} new messages processed.")
            if result and result.state.gmail_action == 'draft':
                drafted = [prospect for prospect, outcome in result.state.outcomes.items() if outcome.status == 'drafted']
                if drafted:
                    message = (f"Saved {len(drafted)} Gmail draft(s) for your request.\n" +
                        '\n'.join(f"To: {result.state.recipients[p].email} — {result.state.drafts[p].subject}" for p in drafted) +
                        "\n\nReview and edit them in Gmail → Drafts, then click Send yourself. Nothing has been sent."
                        f"\nhttps://mail.google.com/mail/#drafts\nRun: {run_id}")
            self._notify(job["id"], message)
        except asyncio.CancelledError:
            self.store.finish_job(job["id"], "interrupted", "Service stopped; inspect and retry.")
            raise
        except Exception as error:
            # Only our own fixed explanations are safe to display. Raw provider
            # errors can contain private prompts, identifiers, or credentials.
            if isinstance(error, ModelProviderError):
                explanation = error.public_message
            elif isinstance(error, LimitExceeded):
                explanation = "This run reached an application usage limit. Inspect its call counts and reserved budget in the dashboard; this is not a provider bill."
            else:
                explanation = "Work could not complete. Inspect the run and connector status in the dashboard."
            self.store.finish_job(job["id"], "failed", f"{type(error).__name__}: {explanation}")
            if job['kind'] == 'chat':
                self._notify(job['id'], f"I couldn't finish that message. {explanation}\nAfter resolving it, retry with /retry {job['run_id']}.")
            else:
                self._notify(job["id"], f"Work {job['id']} failed ({type(error).__name__}). {explanation}\nRun: {job['run_id'] or job['kind']}.")
        finally:
            self.worker_busy = False
        return True

    def _notify(self, job_id, message):
        owner = self.manager.settings.telegram_owner_id
        if owner:
            self.store.notify(f"job:{job_id}", {"chat_id": owner, "text": message})

    async def worker(self):
        while not self.stopping.is_set():
            if not await self.execute_one():
                try: await asyncio.wait_for(self.stopping.wait(), timeout=0.3)
                except TimeoutError: pass

    def list_runs(self, *, page=1, limit=20):
        if page < 1 or not 1 <= limit <= 100: raise ValueError("Invalid pagination.")
        with Session(self.store.engine) as session:
            query = select(RunRow, RunMeta).join(RunMeta, RunMeta.run_id == RunRow.id).where(RunMeta.kind == "outreach")
            total = session.scalar(select(func.count()).select_from(query.subquery()))
            rows = session.execute(query.order_by(RunMeta.created_at.desc(), RunMeta.run_id).offset((page-1)*limit).limit(limit))
            return {"total": total, "page": page, "items": [{"run_id": run.id, "goal": run.payload["goal"],
                "status": run.status, "current_step": self.current_step(run.id, run.payload["current_step"], run.status), "created_at": meta.created_at,
                "origin": meta.origin, "cancel_requested": meta.cancel_requested} for run, meta in rows]}

    def details(self, run_id, *, event_page=1):
        response = self.state(run_id)
        record = self.manager.repository.run(run_id)
        if event_page < 1: raise ValueError("Invalid event page.")
        with Session(self.store.engine) as session:
            total = session.scalar(select(func.count()).select_from(TraceRow).where(TraceRow.run_id == run_id))
            rows = session.scalars(select(TraceRow).where(TraceRow.run_id == run_id).order_by(TraceRow.timestamp.desc(), TraceRow.id).offset((event_page-1)*50).limit(50))
            events = [{"timestamp": r.timestamp, "event": r.event, **r.payload} for r in rows]
        return {**response.model_dump(mode="json"), "status": record["status"], "metadata": self.store.metadata(run_id),
                "current_step": self.current_step(run_id, response.state.current_step, record['status']),
                "usage": {k: record[k] for k in ("model_calls", "search_calls", "estimated_cost")},
                "attached_documents": [{k:v for k,v in self.documents.get(item.document_id).items() if k != 'content'} for item in response.state.attachments],
                "choices": self.choices(run_id), "events": events, "event_total": total, "event_page": event_page}

    def overview(self):
        with Session(self.store.engine) as session:
            job_counts = dict(session.execute(select(JobRow.status, func.count()).group_by(JobRow.status)).all())
            rows = list(session.execute(select(RunRow, RunMeta).join(RunMeta, RunMeta.run_id == RunRow.id)))
            stats = {"runs": 0, "queued": 0, "running": 0, "paused": 0, "completed": 0, "failed": 0, "cancelled": 0,
                     "prospects": 0, "qualified": 0, "pending_approvals": 0, "drafts": 0, "sent": 0, "replies": 0,
                     "model_calls": 0, "search_calls": 0, "browser_pages": 0, "estimated_cost": 0.0, "tokens": 0}
            for row, meta in rows:
                stats["model_calls"] += row.model_calls
                stats["search_calls"] += row.search_calls
                stats["browser_pages"] += meta.browser_calls
                stats["estimated_cost"] += row.estimated_cost
                if meta.kind != "outreach": continue
                stats["runs"] += 1
                if row.status in stats: stats[row.status] += 1
                stats["prospects"] += len(row.payload.get("prospects", []))
                stats["qualified"] += len(row.payload.get("qualified_prospects", []))
                if row.status == "paused": stats["pending_approvals"] += len(row.payload.get("approval_requests", []))
            for action in session.scalars(select(ActionRow).where(ActionRow.status == "done")):
                if action.kind == "send": stats["sent"] += 1
                elif action.kind == "draft": stats["drafts"] += 1
                elif action.kind == "reply": stats["replies"] += 1
            usages = [r.payload.get("usage", {}) for r in session.scalars(select(TraceRow).where(TraceRow.event == "model_end"))]
            stats["tokens"] = sum(u.get("total_tokens", 0) for u in usages)
            stats["token_usage_available"] = any("total_tokens" in u for u in usages)
        return {"stats": stats, "job_counts": job_counts, "queue_paused": self.store.get("queue", {}).get("paused", False),
                "worker_busy": self.worker_busy, "jobs": self.store.jobs(), "recent_runs": self.list_runs(limit=10),
                "last_reply_check": self.store.get("reply_check")}
