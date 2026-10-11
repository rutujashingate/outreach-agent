"""Cooperative cancellation: finish an in-flight call, then stop further work."""
import asyncio

class RunCancelled(Exception):
    pass


class RunStopped(Exception):
    """A resumable owner stop, distinct from permanent cancellation."""


def check_cancelled(repository, run_id):
    from app.storage.control import ControlStore
    store = ControlStore(repository.engine)
    cancelled, stopped = store.work_controls(run_id)
    if cancelled:
        raise RunCancelled("Run cancelled by the owner.")
    if stopped:
        raise RunStopped('Work stopped by the owner; continue resumes it.')


async def acheck_cancelled(repository, run_id):
    """Wait for cloud controls in a thread, leaving Telegram responsive."""
    await asyncio.to_thread(check_cancelled, repository, run_id)
