"""Small, temporary status updates; saved workflow state remains authoritative.

Only fixed stage names reach Telegram. Model thoughts, document contents,
addresses, and credentials never become progress text.
"""
from contextvars import ContextVar
from contextlib import contextmanager
from threading import Lock
import time


_observer = ContextVar('progress_observer', default=None)

NODE_LABELS = {
    'chat_understand': 'Typing…', 'chat_decide': 'Typing…',
    'chat_answer': 'Typing…', 'prepare_documents': 'Researching…',
    'interpret_goal': 'Typing…', 'research': 'Researching…',
    'qualification': 'Researching…', 'prepare_recipients': 'Researching…',
    'choose_recipients': 'Typing…', 'memory_check': 'Researching…',
    'contact_policy': 'Typing…', 'strategy': 'Typing…',
    'writing': 'Typing…', 'review': 'Typing…', 'direct_email': 'Typing…',
    'prepare_approval': 'Typing…', 'human_approval': 'Typing…',
    'external_actions': 'Typing…', 'finish': 'Typing…',
}
TOOL_LABELS = {
    'search': 'Researching…', 'read_page': 'Researching…',
    'read_file': 'Researching…', 'search_saved': 'Researching…',
    'research': 'Researching…', 'run_status': 'Typing…', 'review': 'Typing…',
}


def publish(event, **details):
    """Forward an execution event to this job's observer, without database IO."""
    observer = _observer.get()
    if observer is not None:
        observer(event, details)


class ProgressTracker:
    def __init__(self, clock=time.monotonic):
        self.clock, self._jobs, self._lock = clock, {}, Lock()

    def queued(self, job, *, paused=False):
        if job['kind'] not in {'chat', 'start', 'retry', 'decisions', 'recipients', 'document', 'replies'}:
            return  # Background indexing and validation stay in the dashboard.
        with self._lock:
            # Keep disabled/disconnected Telegram deployments bounded too.
            if len(self._jobs) >= 128:
                for key, item in list(self._jobs.items()):
                    if item['finished'] is not None: self._jobs.pop(key)
                if len(self._jobs) >= 128 and job['id'] not in self._jobs:
                    return
            if paused and job['id'] in self._jobs and self._jobs[job['id']]['started'] is None:
                item = self._jobs[job['id']]
                item.update(label='Queued…', revision=item['revision'] + 1)
            if job['id'] not in self._jobs and job.get('status') in {'queued', 'running'}:
                self._jobs[job['id']] = {
                    'id': job['id'], 'run_id': job.get('run_id'), 'kind': job['kind'],
                    'label': 'Queued…',
                    'created': self.clock(), 'started': None, 'finished': None, 'revision': 0,
                }

    @contextmanager
    def track(self, job):
        self.queued(job)
        initial = {'document': 'Researching…', 'replies': 'Researching…'}
        with self._lock:
            item = self._jobs.get(job['id'])
            if item:
                item.update(started=self.clock(), label=initial.get(job['kind'], 'Typing…'))
                item['revision'] += 1
        token = _observer.set(lambda event, details: self.record(job['id'], event, details))
        try:
            yield
        finally:
            _observer.reset(token)

    def record(self, job_id, event, details):
        label = None
        if event == 'node_start': label = NODE_LABELS.get(details.get('node'))
        elif event == 'tool_start': label = TOOL_LABELS.get(details.get('tool'))
        elif event == 'search_start': label = TOOL_LABELS['search']
        elif event == 'browser_start': label = TOOL_LABELS['read_page']
        elif event == 'model_start':
            label = {'ConversationInstruction': 'Typing…', 'ConversationAction': 'Typing…',
                     'EmailDraft': 'Typing…', 'ReviewResult': 'Typing…',
                     'ResearchResult': 'Researching…', 'ResearchAnalysis': 'Researching…'}.get(details.get('task'))
        if label:
            with self._lock:
                item = self._jobs.get(job_id)
                if item and item['finished'] is None and item['label'] != label:
                    item['label'], item['revision'] = label, item['revision'] + 1

    def finish(self, job_id, status, step=None):
        with self._lock:
            item = self._jobs.get(job_id)
            if item:
                # Telegram removes the progress bubble. The durable final
                # reply explains the result or asks for the owner's decision.
                item.update(finished=self.clock(), status=status)
                item['revision'] += 1

    def snapshot(self):
        with self._lock:
            return [dict(item) for item in self._jobs.values()]

    def finish_waiting(self, run_id, status):
        with self._lock:
            ids = [key for key, item in self._jobs.items() if item['run_id'] == run_id and item['started'] is None]
        for key in ids:
            self.finish(key, status)

    def discard(self, job_id):
        with self._lock:
            self._jobs.pop(job_id, None)
