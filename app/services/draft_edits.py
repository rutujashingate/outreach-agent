"""Prepare Gmail edits, collect exact-content approval, then update once."""
import asyncio
import hashlib
import json
import re
import secrets
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.agent.components.writer import write_draft
from app.agent.components.reviewer import review_draft
from app.agent.context import ManagedModelClient, model_cache_scope
from app.agent.policy import check_contact
from app.connectors.gmail.drafts import snapshot, DraftChanged
from app.connectors.search import ToolError
from app.domain.schemas import EmailDraft, Prospect, OutreachStrategy
from app.domain.workflow import WorkflowState, Sender, Recipient, Outcome
from app.services.cancellation import acheck_cancelled
from app.services.runs import RunConflict
from app.storage.control import ValueRow, JobRow, RunMeta, now
from app.storage.models import RunRow
from app.storage.repository import stable_id
from app.storage.events import atrace


class DraftEdits:
    def __init__(self, service):
        self.service, self.store = service, service.store
        self.manager, self.repository = service.manager, service.manager.repository

    def account(self):
        gmail = self.manager.gmail
        account = gmail.status() if gmail and hasattr(gmail, 'status') else {}
        if not account.get('connected') or not hasattr(gmail, 'read_draft'):
            raise ToolError('Connect Gmail before asking to read or edit a saved draft.')
        return account

    def bound(self, account):
        gmail = self.manager.gmail
        return gmail.for_run(account['email'], account['account_id']) if hasattr(gmail, 'for_run') else gmail

    async def read(self, selector, chat_id):
        """Read one draft, or return choices when an address matches several."""
        account = await asyncio.to_thread(self.account)
        gmail = self.bound(account)
        selector = selector.strip()
        if selector.startswith('id:'):
            identifiers = [selector[3:].strip()]
        elif selector.casefold() in {'', 'latest', 'last', 'most recent'}:
            # The application knows which of its saved drafts was most recent.
            def tracked():
                with Session(self.store.engine) as session:
                    rows = session.scalars(select(RunRow).join(RunMeta, RunMeta.run_id == RunRow.id).order_by(RunMeta.created_at.desc()))
                    for row in rows:
                        if row.payload.get('gmail_account_id') != account.get('account_id'): continue
                        ids = [item['external_id'] for item in row.payload.get('outcomes', {}).values()
                               if item.get('status') in {'drafted', 'updated'} and item.get('external_id')]
                        if ids: return ids[:1]
                return []
            identifiers = await asyncio.to_thread(tracked)
            if not identifiers:
                identifiers = [item['id'] for item in await gmail.list_drafts('', 6)]
        else:
            # The selector is read-only Gmail search data, never an API path.
            match = re.search(r'[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+', selector)
            query = 'to:' + match.group() if match else selector[:200]
            identifiers = [item['id'] for item in await gmail.list_drafts(query, 6)]
        if not identifiers:
            raise ToolError('I could not find that saved Gmail draft. Tell me its recipient or subject.')
        async with asyncio.timeout(self.manager.settings.limits.tool_timeout):
            drafts = [snapshot(await gmail.read_draft(identifier)) for identifier in identifiers[:6]]
        if len(drafts) != 1:
            return {'choices': [{key: item[key] for key in ('draft_id', 'to', 'subject')} for item in drafts],
                    'notice': 'Several drafts match. Ask the owner which subject to edit before continuing.'}
        draft = {**drafts[0], 'account_id': account['account_id'], 'account_email': account['email']}
        if draft['sender'].casefold() != account['email'].casefold():
            raise ToolError('This draft uses a different sender. Edit it in Gmail or reconnect that account.')
        if len(draft['body']) > 50000:
            raise ToolError('This draft is too large to preview safely. Edit it in Gmail.')
        key = 'gmail:snapshot:' + stable_id(chat_id, draft['draft_id'], draft['baseline_hash'])
        await asyncio.to_thread(self.store.put, key, draft)
        return {'snapshot_key': key, 'draft': {k: v for k, v in draft.items() if k != 'raw'}}

    def queue(self, instruction, snapshot_key, key, session_id):
        existing = self.store.find_job(key)
        if existing: return existing
        original = self.store.get(snapshot_key)
        if not original: raise RunConflict('Read the current Gmail draft before proposing an edit.')
        account = self.account()
        if (original['account_id'], original['account_email']) != (account['account_id'], account['email']):
            raise RunConflict('The Gmail account changed. Read the draft again before editing.')
        state = WorkflowState(run_id=uuid4().hex, goal=instruction[:2000], draft_mode='direct', gmail_action='draft',
            gmail_account_id=account['account_id'], sender=Sender(email=account['email']),
            recipients={'draft': Recipient(email=original['to'][0])})
        job = self.store.enqueue('draft_edit_prepare', state.run_id, {'snapshot_key': snapshot_key}, key,
                                 state=state, origin='telegram', run_kind='gmail_edit')
        self.service.tasks.remember(session_id, state.run_id)
        self.service.progress.queued(job)
        return job

    def proposal(self, run_id):
        return self.store.get('gmail_edit:' + run_id)

    def public(self, run_id):
        proposal = self.proposal(run_id)
        if proposal is None: return None
        return {key: value for key, value in proposal.items() if key != 'original'} | {
            'before': {key: proposal['original'][key] for key in ('sender', 'to', 'cc', 'bcc', 'subject', 'body', 'attachment_count')}}

    def preview(self, proposal):
        original, draft = proposal['original'], proposal['draft']
        text = ('Here are my proposed changes. Gmail has not been changed.\n\nFrom: ' + original['sender'] +
                '\nTo: ' + ', '.join(original['to']))
        for field in ('cc', 'bcc'):
            if original[field]: text += '\n' + field.upper() + ': ' + ', '.join(original[field])
        return (text + f"\nAttachments retained: {original['attachment_count']}\n\nPrevious subject: {original['subject']}" +
                f"\nPrevious message{' (first 1,000 characters)' if len(original['body']) > 1000 else ''}:\n{original['body'][:1000]}\n" +
                f"\nNew subject: {draft['subject']}\n\n{draft['body']}\n\nApprove to update this same Gmail draft. Nothing will be sent.")

    def entries(self, run_id):
        proposal = self.proposal(run_id)
        if not proposal or proposal['status'] != 'pending': return []
        common = {'gmail_edit': run_id, 'fingerprint': proposal['fingerprint']}
        return [('Approve changes', {**common, 'edit_decision': 'approve'}),
                ('Reject changes', {**common, 'edit_decision': 'reject'})]

    async def prepare(self, job):
        run_id = job['run_id']
        await acheck_cancelled(self.repository, run_id)
        proposal = await asyncio.to_thread(self.proposal, run_id)
        state = (await asyncio.to_thread(self.service.state, run_id)).state
        await asyncio.to_thread(self.repository.save_run, state, 'running')
        if proposal is None:
            original = await asyncio.to_thread(self.store.get, job['payload']['snapshot_key'])
            if original is None: raise RunConflict('The saved draft snapshot is missing. Read it again.')
            account = await asyncio.to_thread(self.account)
            if account['account_id'] != original['account_id']:
                raise RunConflict('The Gmail account changed. Read the draft again.')
            prospect = Prospect(id='draft', company_name=original['to'][0], entity_type='person')
            strategy = OutreachStrategy(prospect_id='draft', trigger='Owner requested an edit.',
                pain_hypothesis='Do not invent facts.', value_proposition=state.goal,
                personalization_hook='Preserve the existing message except for requested changes.',
                call_to_action='Keep the existing request unless asked to change it.')
            previous = (EmailDraft(prospect_id='draft', subject=original['subject'] or '(no subject)', body=original['body'])
                        if original['body'].strip() else None)
            feedback = [state.goal]
            async with self.manager.client_factory() as client:
                managed = ManagedModelClient(client, self.repository, run_id, self.manager.settings.limits)
                for attempt in range(self.manager.settings.limits.max_revisions + 1):
                    scope = model_cache_scope.set('gmail_edit:write:' + str(attempt))
                    try:
                        draft = await write_draft(prospect, strategy, [], state.sender, managed, previous=previous,
                            feedback=feedback, brief={'goal': state.goal, 'editing_existing_draft': True,
                            'original_subject': original['subject'], 'original_body': original['body']})
                    finally: model_cache_scope.reset(scope)
                    scope = model_cache_scope.set('gmail_edit:review:' + str(attempt))
                    try:
                        review = await review_draft(prospect, strategy, [], state.sender, draft, managed,
                            brief={'goal': state.goal, 'editing_existing_draft': True, 'original_subject': original['subject'], 'original_body': original['body']})
                    finally: model_cache_scope.reset(scope)
                    if review.approved: break
                    previous, feedback = draft, [state.goal, *review.issues]
            await acheck_cancelled(self.repository, run_id)
            state.drafts, state.reviews, state.draft_versions = {'draft': draft}, {'draft': review}, {'draft': 1}
            if not review.approved:
                state.current_step = 'failed'
                await asyncio.to_thread(self.repository.save_run, state, 'failed', 'The proposed edit did not pass automated review.')
                await asyncio.to_thread(self.service._notify, job['id'], 'I could not prepare a suitable edit. Your Gmail draft is unchanged. Check the review in the dashboard.')
                return 'failed'
            identity = {'run_id': run_id, 'account': original['account_id'], 'draft_id': original['draft_id'], 'baseline': original['baseline_hash'],
                        'draft': draft.model_dump(), 'action': 'update_draft', 'version': 1}
            proposal = {'run_id': run_id, 'status': 'pending', 'original': original, 'draft': draft.model_dump(),
                        'fingerprint': hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest(), 'version': 1}
            await asyncio.to_thread(self.store.put, 'gmail_edit:' + run_id, proposal)
        state.drafts = {'draft': EmailDraft.model_validate(proposal['draft'])}
        state.current_step = 'awaiting_approval'
        await asyncio.to_thread(self.repository.save_run, state, 'paused')
        await asyncio.to_thread(self.service._notify, job['id'], self.preview(proposal), self.entries(run_id))
        return 'paused'

    def decide(self, run_id, fingerprint, decision):
        """Save approval and its job together; races/repeated clicks cannot write twice."""
        if decision not in {'approve', 'reject'}: raise ValueError('Choose approve or reject.')
        key = 'gmail-edit:apply:' + run_id + ':' + fingerprint
        with Session(self.store.engine) as session, session.begin():
            row = session.scalar(select(ValueRow).where(ValueRow.key == 'gmail_edit:' + run_id).with_for_update())
            if row is None or not secrets.compare_digest(row.value['fingerprint'], fingerprint):
                raise RunConflict('These changes are no longer current. Request a new preview.')
            proposal = row.value
            if decision == 'approve':
                account = self.account()
                if (account['account_id'], account['email']) != (proposal['original']['account_id'], proposal['original']['account_email']):
                    raise RunConflict('The Gmail account changed. Read the draft and request a new preview.')
            existing = session.scalar(select(JobRow).where(JobRow.request_key == key))
            if existing:
                return {'status': proposal['status'], 'job_id': existing.id, 'run_id': run_id}
            if proposal['status'] != 'pending': raise RunConflict('This edit decision has already been resolved.')
            run = session.get(RunRow, run_id)
            meta = session.get(RunMeta, run_id)
            if meta.cancel_requested or run.status != 'paused':
                raise RunConflict('This edit is cancelled or is no longer awaiting approval.')
            proposal = {**proposal, 'status': 'approved' if decision == 'approve' else 'rejected'}
            changed = session.execute(update(ValueRow).where(ValueRow.key == row.key,
                ValueRow.value['status'].as_string() == 'pending').values(value=proposal))
            if changed.rowcount != 1: raise RunConflict('An edit decision has already been recorded.')
            if decision == 'reject':
                state = WorkflowState.model_validate(run.payload)
                state.current_step = 'cancelled'
                run.payload, run.status = state.model_dump(mode='json'), 'cancelled'
                return {'status': 'rejected', 'run_id': run_id}
            job_id = uuid4().hex
            session.add(JobRow(id=job_id, request_key=key, run_id=run_id, kind='draft_edit_apply', payload={'fingerprint': fingerprint}))
            run.status = 'queued'
            return {'status': 'approved', 'job_id': job_id, 'run_id': run_id}

    async def apply(self, job):
        run_id = job['run_id']
        await acheck_cancelled(self.repository, run_id)
        proposal = await asyncio.to_thread(self.proposal, run_id)
        if not proposal or proposal['fingerprint'] != job['payload'].get('fingerprint') or proposal['status'] not in {'approved', 'updated'}:
            raise RunConflict('Approval is missing or no longer matches this edit.')
        original = proposal['original']
        account = await asyncio.to_thread(self.account)
        if account['account_id'] != original['account_id'] or account['email'] != original['account_email']:
            raise RunConflict('The Gmail account changed. Request a new preview.')
        key = stable_id('gmail-edit', proposal['fingerprint'])
        prior = await asyncio.to_thread(self.repository.action, key)
        if prior:
            if prior['status'] == 'done':
                return await self._finish(job, proposal, 'updated', 'Your changes are saved in the same Gmail draft. You can review and send it yourself in Gmail.')
            raise RunConflict('The earlier update needs inspection in Gmail; it will not be repeated automatically.')
        recipients = sorted(set(original['to'] + original['cc'] + original['bcc']))
        acquired = []
        try:
            for address in recipients:
                decision = await asyncio.to_thread(check_contact, self.repository, Recipient(email=address), self.manager.settings.limits, cold_outreach=False)
                if not decision.allowed: raise RunConflict('A recipient contact check blocked this edit. Inspect the dashboard.')
                if not await asyncio.to_thread(self.repository.claim_contact_action, address, key):
                    raise RunConflict('Another action is already using this recipient. Try again after it finishes.')
                acquired.append(address)
            # This is the last safe stop boundary before reserving a Gmail
            # write. Once reserved, finish recording its result before stopping.
            await acheck_cancelled(self.repository, run_id)
            if not await asyncio.to_thread(self.repository.claim_action, key, recipients[0], 'update_draft'):
                raise RunConflict('This update is already recorded. Inspect the draft before trying again.')
        except BaseException:
            for address in acquired: await asyncio.to_thread(self.repository.release_contact_action, address, key)
            raise
        await atrace(self.repository, run_id, 'external_action_start', action='update_draft', action_key=key)
        try:
            async with asyncio.timeout(self.manager.settings.limits.tool_timeout):
                await self.bound(account).update_draft(original['draft_id'], original['baseline_hash'], EmailDraft.model_validate(proposal['draft']))
        except DraftChanged:
            await asyncio.to_thread(self.repository.finish_action, key, 'blocked', {'run_id': run_id})
            for address in acquired: await asyncio.to_thread(self.repository.release_contact_action, address, key)
            return await self._finish(job, proposal, 'blocked', 'The draft changed in Gmail after this preview. I left it unchanged. Ask for a new edit preview.')
        except Exception:
            await asyncio.to_thread(self.repository.finish_action, key, 'uncertain', {'run_id': run_id})
            return await self._finish(job, proposal, 'uncertain', 'Gmail did not confirm the update. Please inspect the draft before another attempt; I will not repeat it automatically.')
        await asyncio.to_thread(self.repository.finish_action, key, 'done', {'run_id': run_id, 'draft_id': original['draft_id']})
        for address in acquired: await asyncio.to_thread(self.repository.release_contact_action, address, key)
        await atrace(self.repository, run_id, 'external_action_end', action='update_draft', external_id=original['draft_id'])
        return await self._finish(job, proposal, 'updated', 'Your changes are saved in the same Gmail draft. You can review and send it yourself in Gmail.')

    async def _finish(self, job, proposal, outcome, message):
        run_id = job['run_id']
        state = (await asyncio.to_thread(self.service.state, run_id)).state
        state.current_step = 'completed'
        state.outcomes = {'draft': Outcome(prospect_id='draft', status=outcome, source='gmail:' + proposal['original']['draft_id'],
            external_id=proposal['original']['draft_id'], message_fingerprint=proposal['fingerprint'])}
        await asyncio.to_thread(self.repository.save_run, state, 'completed')
        await asyncio.to_thread(self.store.put, 'gmail_edit:' + run_id, {**proposal, 'status': outcome})
        await asyncio.to_thread(self.service._notify, job['id'], message)
        return 'completed'

    def retry(self, run_id, key):
        proposal = self.proposal(run_id)
        if proposal and proposal['status'] in {'uncertain', 'blocked', 'rejected', 'updated'}:
            raise RunConflict('Inspect Gmail and request a new edit preview; this update cannot be replayed.')
        with Session(self.store.engine) as session:
            original = session.scalar(select(JobRow).where(JobRow.run_id == run_id, JobRow.kind == 'draft_edit_prepare'))
            payload = original.payload
        if proposal and proposal['status'] == 'approved':
            return self.store.enqueue('draft_edit_apply', run_id, {'fingerprint': proposal['fingerprint']}, key)
        return self.store.enqueue('draft_edit_prepare', run_id, payload, key)
