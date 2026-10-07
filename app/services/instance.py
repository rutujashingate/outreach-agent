"""Keep one server process in charge of the SQLite job queue and Telegram bot."""
from contextlib import contextmanager
import fcntl
import os


@contextmanager
def instance_lock(directory):
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    file = open(directory / 'service.lock', 'a+')
    os.chmod(directory / 'service.lock', 0o600)
    try:
        try: fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise RuntimeError('Another outreach service is using this data directory.') from None
        file.seek(0); file.truncate(); file.write(str(os.getpid())); file.flush()
        yield
    finally: file.close()
