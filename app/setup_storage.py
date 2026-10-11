"""Provision app-owned storage without displaying credentials or calling an LLM.

Run --download-model once for local embeddings. --fresh-start also backs up
SQLite and preserves Telegram's processed-update cursor; it never imports old
runs or deletes either database.
"""
import argparse
import asyncio
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sqlite3

from dotenv import load_dotenv

from app.connectors.search import ToolError
from app.llm.embeddings import LocalEmbeddings
from app.services.instance import instance_lock
from app.services.runtime import open_runtime
from app.services.application import AgentService
from app.services.storage_validation import validate_storage
from app.settings import Settings
from app.storage.files import SupabaseFiles


def backup_local(directory):
    """Return a backup folder and the existing acknowledged Telegram cursor."""
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target = directory / 'backups' / stamp
    target.mkdir(parents=True, mode=0o700)
    cursor = None
    for file in directory.glob('*.sqlite3'):
        source = sqlite3.connect(file.resolve().as_uri() + '?mode=ro', uri=True)
        try:
            with sqlite3.connect(target / file.name) as copy: source.backup(copy)
            (target / file.name).chmod(0o600)
            if file.name == 'relationships.sqlite3':
                import json
                row = source.execute("SELECT value FROM service_values WHERE key='telegram_offset'").fetchone()
                if row: cursor = json.loads(row[0])
        finally: source.close()
    if (directory / 'uploads').exists(): shutil.copytree(directory / 'uploads', target / 'uploads')
    return target, cursor


async def setup(settings, *, download_model=False, fresh_start=False):
    if download_model:
        await LocalEmbeddings(settings.data_dir / 'models').prepare(download=True)
        print('Local embedding model is cached and ready.')
    if not settings.supabase_database_url:
        if download_model: return
        raise ToolError('Add the Supabase database URL to .env before provisioning cloud storage.')
    with instance_lock(settings.data_dir):
        cursor = None
        if fresh_start:
            backup, cursor = backup_local(settings.data_dir)
            print('Local records backed up to ' + str(backup))
        async with open_runtime(settings) as manager:
            service = AgentService(manager)
            if fresh_start:
                from sqlalchemy import func, select
                from sqlalchemy.orm import Session
                from app.storage.models import RunRow
                with Session(service.store.engine) as session:
                    if session.scalar(select(func.count()).select_from(RunRow)):
                        raise ToolError('The cloud database already has runs. Omit --fresh-start; no records were deleted.')
                if cursor is not None and service.store.get('telegram_offset') is None:
                    service.store.put('telegram_offset', cursor)
            if settings.document_storage == 'supabase':
                await service.documents.files.ensure_bucket()
                print('Private document bucket is ready.')
            print('Application tables, indexes, and LangGraph checkpoints are ready.')
            report = await validate_storage(service)
            for check in report['checks']: print(check['name'] + ': ' + check['status'])
            if report['status'] != 'passed':
                raise ToolError('Some storage checks failed. Inspect Connections → Saved state after starting the service.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download-model', action='store_true')
    parser.add_argument('--fresh-start', action='store_true')
    args = parser.parse_args()
    load_dotenv()
    try:
        settings = Settings.from_env()
        asyncio.run(setup(settings, download_model=args.download_model, fresh_start=args.fresh_start))
    except Exception as error:
        # Never print arbitrary database or HTTP exception bodies.
        print(str(error) if isinstance(error, ToolError) else
              'Storage setup failed. Stop the service, check configuration, database access, and pgvector availability; then retry.')
        raise SystemExit(1) from None


if __name__ == '__main__': main()
