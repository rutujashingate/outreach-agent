"""Owner-requested write/read checks with isolated, removable test data."""
import time
from uuid import uuid4

from langgraph.checkpoint.base import empty_checkpoint
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.connectors.search import ToolError
from app.storage.control import ValueRow, now
from app.storage.knowledge import KnowledgeChunk, KnowledgeSource
from app.services.knowledge import capture_source


async def validate_storage(service):
    nonce = uuid4().hex
    key, thread_id, object_key = 'validation:' + nonce, 'storage-validation:' + nonce, 'validation/' + nonce
    report = {'status': 'running', 'started_at': now(), 'checks': []}
    service.store.put('storage:validation', report)
    source_id = None

    async def check(name, function):
        started = time.monotonic()
        try:
            await function()
            item = {'name': name, 'status': 'passed'}
        except Exception as error:
            # Fixed messages only: driver/HTTP exceptions can contain secrets.
            item = {'name': name, 'status': 'failed', 'error': {
                'database': 'Database write/read failed.',
                'checkpoint': 'Checkpoint write/read failed.',
                'files': 'Private file write/read failed. Check the bucket and server key.',
                'private_access': 'Private access could not be verified.',
                'semantic_search': 'Embedding or retrieval check failed. Download the model and inspect indexing.',
                'cleanup': 'Temporary test data could not all be removed. Inspect storage before retrying.'}[name],
                'error_type': type(error).__name__}
        item['duration_ms'] = round((time.monotonic() - started)*1000)
        report['checks'].append(item)
        service.store.put('storage:validation', report)

    async def database():
        service.store.put(key, {'nonce': nonce})
        if service.store.get(key) != {'nonce': nonce}: raise ToolError('Database round trip failed.')

    async def checkpoint():
        saver = service.manager.checkpointer
        config = {'configurable': {'thread_id': thread_id, 'checkpoint_ns': ''}}
        saved = empty_checkpoint()
        saved['channel_values'] = {'probe': nonce}
        saved['channel_versions'] = {'probe': '1'}
        await saver.aput(config, saved, {'source': 'input', 'step': -1, 'parents': {}}, {'probe': '1'})
        result = await saver.aget(config)
        if not result or result['channel_values'].get('probe') != nonce: raise ToolError('Checkpoint round trip failed.')

    async def files():
        await service.documents.files.put(object_key, nonce.encode())
        if await service.documents.files.get(object_key) != nonce.encode(): raise ToolError('File round trip failed.')

    async def private_access():
        files = service.documents.files
        if hasattr(files, 'anonymous_denied') and not await files.anonymous_denied(object_key):
            raise ToolError('Anonymous file read succeeded.')
        engine = service.manager.repository.engine
        if service.manager.settings.supabase_database_url:
            with engine.connect() as connection:
                for role in ('anon', 'authenticated', 'service_role'):
                    if connection.execute(text('SELECT 1 FROM pg_roles WHERE rolname=:role'), {'role': role}).scalar():
                        if connection.execute(text("SELECT has_schema_privilege(:role, 'outreach', 'USAGE')"), {'role': role}).scalar():
                            raise ToolError('Private table grants are too broad.')

    async def semantic():
        nonlocal source_id
        if not service.manager.settings.semantic_search_enabled:
            raise ToolError('Enable semantic search to validate embeddings.')
        source_id = capture_source(service.store.engine, kind='validation', ref='validation:' + nonce,
            label='Temporary validation passage', purpose='background', retrieved_at=now(),
            pages=[{'number': 1, 'text': 'Cobalt otters measure API latency. Validation identifier ' + nonce}])
        await service.knowledge.index(source_id)
        result = await service.knowledge.search('Cobalt otters measure API latency ' + nonce)
        if result['mode'] != 'hybrid' or not any(item['source_id'] == source_id for item in result['matches']):
            raise ToolError('Semantic retrieval did not recover its test passage.')

    async def cleanup():
        failures = []
        for function in (lambda: service.documents.files.delete(object_key),
                         lambda: service.manager.checkpointer.adelete_thread(thread_id)):
            try: await function()
            except Exception: failures.append(True)
        try:
            service.store.delete(key)
            with Session(service.store.engine) as session, session.begin():
                if source_id:
                    session.execute(delete(KnowledgeChunk).where(KnowledgeChunk.source_id == source_id))
                    session.execute(delete(KnowledgeSource).where(KnowledgeSource.id == source_id))
                    # Probe indexing was executed directly, not by the worker.
                    from app.storage.control import JobRow
                    for row in session.scalars(select(JobRow).where(JobRow.kind == 'knowledge')):
                        if row.payload.get('source_id') == source_id: session.delete(row)
        except Exception: failures.append(True)
        if failures: raise ToolError('Cleanup needs inspection.')

    try:
        for name, function in [('database', database), ('checkpoint', checkpoint), ('files', files),
                               ('private_access', private_access), ('semantic_search', semantic)]:
            if name == 'semantic_search' and not service.manager.settings.semantic_search_enabled:
                report['checks'].append({'name': name, 'status': 'skipped', 'duration_ms': 0,
                                        'reason': 'Semantic search is disabled.'})
                continue
            await check(name, function)
    finally:
        await check('cleanup', cleanup)
        report['status'] = 'passed' if all(item['status'] in {'passed', 'skipped'} for item in report['checks']) else 'failed'
        report['finished_at'] = now()
        service.store.put('storage:validation', report)
    return report
