"""Remember which work belongs to a conversation and resume it explicitly."""
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.services.runs import RunConflict, RunNotFound
from app.storage.control import JobRow, ValueRow, now
from app.storage.events import trace
from app.storage.models import RunRow


class TaskControls:
    def __init__(self, service):
        self.service, self.store = service, service.store

    def remember(self, session_id, run_id):
        """Link a task to its conversation without relying on recent chat text."""
        key = 'tasks:' + session_id
        with Session(self.store.engine) as session, session.begin():
            row = session.get(ValueRow, key)
            ids = list(row.value.get('run_ids', [])) if row else []
            if run_id not in ids:
                ids.append(run_id)
            statuses = dict(session.execute(select(RunRow.id, RunRow.status).where(RunRow.id.in_(ids))).all())
            finished = [identifier for identifier in ids if statuses.get(identifier) in {'completed', 'cancelled'}]
            recent_finished = set(finished[-20:])
            # A long conversation must not evict an unfinished task merely
            # because the owner asked many unrelated questions afterward.
            retained = [identifier for identifier in ids if identifier in recent_finished or
                        statuses.get(identifier) not in {'completed', 'cancelled'}]
            session.merge(ValueRow(key=key, value={'run_ids': retained}))

    def select(self, session_id, run_id=''):
        """Resolve one task. Multiple unfinished tasks need an explicit ID."""
        repository = self.service.manager.repository
        if run_id:
            row = repository.run(run_id)
            if row is None or (self.store.metadata(run_id) or {}).get('kind') not in {'chat', 'outreach'}:
                raise RunNotFound('Unknown conversation or outreach task.')
            return run_id, row
        ids = self.store.get('tasks:' + session_id, {}).get('run_ids', [])
        # Adopt older chat turns that predate the task index. Reading the saved
        # job payload also repairs a crash immediately after enqueueing a turn.
        if not ids:
            with Session(self.store.engine) as session:
                jobs = session.scalars(select(JobRow).where(JobRow.kind == 'chat').order_by(JobRow.created_at.desc()))
                ids = list(dict.fromkeys(job.run_id for job in jobs if job.payload.get('session_id') == session_id))[:50]
            ids.reverse()
        candidates = [(identifier, repository.run(identifier)) for identifier in ids]
        candidates = [(identifier, row) for identifier, row in candidates if row]
        unfinished = [(identifier, row) for identifier, row in candidates
                      if row['status'] in {'queued', 'running', 'failed', 'stopped', 'paused'}]
        if len(unfinished) > 1:
            raise RunConflict('Several tasks are unfinished. Choose one with /continue RUN_ID:\n' +
                '\n'.join(f"{identifier} — {row['state']['goal'][:100]} ({row['status']})" for identifier, row in unfinished[-5:]))
        if unfinished:
            return unfinished[0]
        if candidates:
            return candidates[-1]
        raise RunConflict('There is no saved task in this conversation. Tell me what to work on, or use /continue RUN_ID for an earlier task.')

    def stop(self, run_id):
        """Let an in-flight operation record its result, then stop at a boundary."""
        _, row = self.select('', run_id)
        if row['status'] in {'completed', 'cancelled'}:
            raise RunConflict('This task has ended. Start a new request if you need more work.')
        if row['status'] == 'paused':
            return {'run_id': run_id, 'status': 'paused', 'message': 'This task is already waiting for your decision.'}
        self.store.put('stop:' + run_id, {'requested': True})
        with Session(self.store.engine) as session, session.begin():
            session.execute(update(JobRow).where(JobRow.run_id == run_id, JobRow.status == 'queued')
                            .values(status='stopped', updated_at=now()))
        if row['status'] != 'running':
            state = self.service.state(run_id).state
            state.current_step = 'stopped'
            self.service.manager.repository.save_run(state, 'stopped')
            self.service.progress.finish_waiting(run_id, 'stopped')
        trace(self.service.manager.repository, run_id, 'stop_requested')
        return {'run_id': run_id, 'status': 'stop_requested',
                'message': 'Stop requested. The current call can finish saving its result. Say continue to resume this task.'}

    async def continue_task(self, session_id, key, run_id=''):
        existing = self.store.find_job(key)
        if existing:
            return {'run_id': existing['run_id'], 'job': existing, 'message': 'Continuation is already queued.'}
        run_id, row = self.select(session_id, run_id)
        goal = row['state']['goal']
        prefix = f'Task: {goal}\nRun: {run_id}\n'
        if row['status'] in {'queued', 'running'}:
            status = 'finishing its current call before stopping' if self.store.get('stop:' + run_id, {}).get('requested') else row['status']
            return {'run_id': run_id, 'message': prefix + f'This task is already {status}. No duplicate was started.'}
        if row['status'] in {'completed', 'cancelled'}:
            return {'run_id': run_id, 'message': prefix + f'This task is {row["status"]}. Describe the additional work as a new request.'}
        kind = self.store.metadata(run_id)['kind']
        graph = self.service.conversations.graph if kind == 'chat' else self.service.manager.graph
        config = self.service.conversations.config(run_id) if kind == 'chat' else self.service.manager.config(run_id)
        snapshot = await graph.aget_state(config)
        # A generic continue is never a recipient selection or draft approval.
        if row['status'] == 'paused' or any(task.interrupts for task in snapshot.tasks):
            if snapshot.values and kind == 'outreach' and row['status'] != 'paused':
                from app.domain.workflow import WorkflowState
                self.service.manager.repository.save_run(WorkflowState.model_validate(snapshot.values), 'paused')
            self.store.delete('stop:' + run_id)
            response = self.service.state(run_id)
            command = '/recipients' if response.awaiting_recipients else '/review'
            return {'run_id': run_id, 'message': prefix + f'I still need your decision. Use {command} {run_id} or open this run in the dashboard.'}
        next_steps = list(snapshot.next) or ['save the completed result' if snapshot.values else 'start the saved request']
        # Keep the same run ID, counters, sources, account binding, and action
        # ledger. Only the owner's resumable-stop flag is cleared by retry().
        job = self.service.retry(run_id, key)
        trace(self.service.manager.repository, run_id, 'continue_requested', next_steps=next_steps)
        message = prefix + 'Continuing from: ' + ', '.join(next_steps) + '.'
        if self.store.get('queue', {}).get('paused'):
            message += ' The job is saved; resume the queue in the dashboard to execute it.'
        return {'run_id': run_id, 'job': job, 'message': message}
