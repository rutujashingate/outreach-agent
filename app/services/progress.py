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
    'chat_understand': 'Thinking…', 'chat_decide': 'Planning the next step…',
    'chat_answer': 'Preparing your reply…', 'prepare_documents': 'Reading your files…',
    'interpret_goal': 'Understanding your goal…', 'research': 'Researching…',
    'qualification': 'Checking prospect matches…', 'prepare_recipients': 'Checking recipient addresses…',
    'choose_recipients': 'Waiting for your recipient choices.', 'memory_check': 'Checking previous conversations…',
    'contact_policy': 'Checking contact rules…', 'strategy': 'Planning the emails…',
    'writing': 'Drafting emails…', 'review': 'Reviewing the drafts…',
    'prepare_approval': 'Preparing drafts for review…', 'human_approval': 'Waiting for your review.',
    'external_actions': 'Saving the requested Gmail drafts…', 'finish': 'Saving the result…',
}
TOOL_LABELS = {
    'search': 'Searching the web…', 'read_page': 'Reading a website…',
    'read_file': 'Reading your file…', 'search_saved': 'Searching saved documents…',
    'research': 'Analyzing the research…', 'run_status': 'Checking saved task progress…',
    'review': 'Reading the draft review…',
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
                item.update(label='Queue paused — your request is saved.', revision=item['revision'] + 1)
            if job['id'] not in self._jobs and job.get('status') in {'queued', 'running'}:
                self._jobs[job['id']] = {
                    'id': job['id'], 'run_id': job.get('run_id'), 'kind': job['kind'],
                    'label': 'Queue paused — your request is saved.' if paused else 'Queued — waiting for the worker.',
                    'created': self.clock(), 'started': None, 'finished': None, 'revision': 0,
                }

    @contextmanager
    def track(self, job):
        self.queued(job)
        initial = {'chat': 'Thinking…', 'document': 'Reading your file…', 'replies': 'Checking Gmail replies…'}
        with self._lock:
            item = self._jobs.get(job['id'])
            if item:
                item.update(started=self.clock(), label=initial.get(job['kind'], 'Working on your request…'))
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
            label = {'ConversationInstruction': 'Thinking…', 'ConversationAction': 'Thinking…',
                     'EmailDraft': 'Drafting emails…', 'ReviewResult': 'Reviewing the drafts…',
                     'ResearchResult': 'Analyzing the research…', 'ResearchAnalysis': 'Analyzing the research…'}.get(details.get('task'))
        if label:
            with self._lock:
                item = self._jobs.get(job_id)
                if item and item['finished'] is None and item['label'] != label:
                    item['label'], item['revision'] = label, item['revision'] + 1

    def finish(self, job_id, status, step=None):
        with self._lock:
            item = self._jobs.get(job_id)
            if item:
                label = {'failed': 'Could not finish. Check the error message and dashboard.',
                         'interrupted': 'Interrupted. Your saved task can be retried.',
                         'stopped': 'Stopped — progress saved. Say continue to resume.',
                         'cancelled': 'Task cancelled.'}.get(status)
                if label is None:
                    label = {'awaiting_recipients': 'Waiting for your recipient choices.',
                             'awaiting_approval': 'Drafts ready for your review.'}.get(step)
                item.update(finished=self.clock(), label=label or 'Finished — the result is ready.')
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
