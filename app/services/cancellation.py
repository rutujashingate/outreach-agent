"""Cooperative cancellation: finish an in-flight call, then stop further work."""
class RunCancelled(Exception):
    pass


def check_cancelled(repository, run_id):
    from app.storage.control import ControlStore
    if ControlStore(repository.engine).cancellation_requested(run_id):
        raise RunCancelled("Run cancelled by the owner.")
