"""Cooperative cancellation: finish an in-flight call, then stop further work."""
class RunCancelled(Exception):
    pass


class RunStopped(Exception):
    """A resumable owner stop, distinct from permanent cancellation."""


def check_cancelled(repository, run_id):
    from app.storage.control import ControlStore
    store = ControlStore(repository.engine)
    if store.cancellation_requested(run_id):
        raise RunCancelled("Run cancelled by the owner.")
    if store.get('stop:' + run_id, {}).get('requested'):
        raise RunStopped('Work stopped by the owner; continue resumes it.')
