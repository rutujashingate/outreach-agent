"""Keep idle background services alive through temporary database outages."""
import asyncio
import logging

from sqlalchemy.exc import InterfaceError, OperationalError, TimeoutError as PoolTimeout


TRANSIENT_DATABASE_ERRORS = (InterfaceError, OperationalError, PoolTimeout)
logger = logging.getLogger(__name__)


async def wait_or_stop(stop, seconds):
    """Wait without delaying shutdown when the service is asked to stop."""
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except TimeoutError:
        pass


async def run_loop(name, stop, step, health, *, idle_delay=1, retry_delay=5):
    """Run the next safe iteration, backing off after database failures.

    A worker iteration claims queued work only; it never reclaims a running
    job. Telegram keeps its saved update IDs and delivery ledger. Consequently
    this loop does not replay an interrupted model call or uncertain send.
    Unknown programming errors still surface as failed tasks in /health.
    """
    failures = 0
    while not stop.is_set():
        try:
            worked = await step()
        except TRANSIENT_DATABASE_ERRORS as error:
            failures += 1
            health[name] = {'status': 'retrying', 'error_type': type(error).__name__}
            # Exception messages can include credentials or SQL parameters.
            if failures == 1:
                logger.warning('%s waiting for database (%s)', name, type(error).__name__)
            await wait_or_stop(stop, min(30, retry_delay * 2 ** min(failures - 1, 3)))
        else:
            if failures:
                logger.info('%s database connection recovered', name)
            failures = 0
            health[name] = {'status': 'running'}
            if not worked:
                await wait_or_stop(stop, idle_delay)


def observe_task(task, health, stopping):
    """Record an unexpected task exit without logging private exception text."""
    name = task.get_name()
    if task.cancelled():
        health[name] = {'status': 'cancelled'}
    else:
        error = task.exception()
        health[name] = {'status': 'failed' if error else 'stopped'}
        if error:
            health[name]['error_type'] = type(error).__name__
    if not stopping.is_set():
        logger.error('%s stopped (%s)', name, health[name].get('error_type', health[name]['status']))
