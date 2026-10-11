"""Saved evidence stays private, searchable, and reusable after a restart."""
import asyncio
from hashlib import sha256
import json
from pathlib import Path
from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.connectors.browser.client import FakeBrowser
from app.connectors.browser.managed import ManagedBrowser
from app.connectors.search import ToolError
from app.domain.browser import PageEvidence
from app.domain.conversation import ConversationAction
from app.llm.client import ModelResponseError
from app.llm.embeddings import FakeEmbeddings, LocalEmbeddings, DIMENSION, checked_vectors
from app.llm.tools import checked_call, tool_definitions
from app.main import create_app
from app.services.application import AgentService
from app.services.knowledge import KnowledgeService, capture_source
from app.services.storage_validation import validate_storage
from app.services.runtime import open_runtime
from app.settings import Settings
from app.setup_storage import backup_local
from app.storage.control import ControlStore, now
from app.storage.database import create_database
from app.storage.files import BUCKET, FakeFiles, SupabaseFiles
from app.storage.knowledge import KnowledgeChunk, KnowledgeSource
from app.storage.repository import Repository
from test_supabase_storage import postgres_cluster, postgres_url


def source(engine, value='API observability measures latency.', ref='https://example.com/research', kind='website'):
    return capture_source(engine, kind=kind, ref=ref, label='Example source',
        pages=[{'number': 2, 'text': value}], retrieved_at=now(), purpose='research' if kind=='website' else 'background')


@pytest.mark.parametrize('changes', [
    {'supabase_url': 'http://project.supabase.co'}, {'supabase_url': 'https://evil.example'},
    {'supabase_secret_key': ''}, {'supabase_database_url': None},
    {'supabase_url': 'https://project.supabase.co/private'},
])
def test_cloud_configuration_rejects_missing_or_unsafe_credentials(changes):
    values = {'supabase_database_url': 'postgresql://owner:private-password@host:5432/postgres',
              'supabase_url': 'https://project.supabase.co', 'supabase_secret_key': 'sb_secret_private', 'document_storage': 'supabase'}
    with pytest.raises(ValueError) as error: Settings(**{**values, **changes})
    assert 'private-password' not in str(error.value) and 'sb_secret_private' not in str(error.value)


def test_cloud_settings_hide_the_database_password_and_storage_key():
    settings = Settings(supabase_database_url='postgresql://owner:private-password@host:5432/postgres',
                        supabase_url='https://project.supabase.co', supabase_secret_key='sb_secret_private', document_storage='supabase')
    assert 'private-password' not in repr(settings) + settings.model_dump_json()
    assert 'sb_secret_private' not in repr(settings) + settings.model_dump_json()


@pytest.mark.parametrize('missing_code', [400,404])
def test_setup_creates_private_bucket_and_reconciles_uncertain_upload(missing_code):
    objects, calls, created = {}, [], []
    key = 'originals/' + 'a'*32
    def handle(request):
        calls.append(request)
        assert request.headers.get('apikey') == 'sb_secret_test'
        assert 'authorization' not in request.headers
        path = request.url.path
        if path == '/storage/v1/bucket/' + BUCKET:
            return httpx.Response(200, json={'public':False,'file_size_limit':10*1024*1024}) if created else httpx.Response(missing_code,json={'message':'Bucket not found'})
        if path == '/storage/v1/bucket':
            assert json.loads(request.content)['public'] is False
            created.append(True); return httpx.Response(200,json={})
        if request.method == 'POST':
            objects[key] = request.content
            raise httpx.ReadTimeout('Lost upload response', request=request)
        return httpx.Response(200,content=objects[key])
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            files = SupabaseFiles(Settings(supabase_url='https://project.supabase.co',supabase_secret_key='sb_secret_test'), http)
            await files.ensure_bucket()
            await files.put(key,b'original text')
            assert await files.get(key)==b'original text'
        assert len(objects)==1
    asyncio.run(check())


def test_storage_rejects_public_bucket_and_credential_redirect():
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200,json={'public':True}))) as http:
            with pytest.raises(ToolError,match='private'):
                await SupabaseFiles(Settings(supabase_url='https://project.supabase.co'),http).ensure_bucket()
        calls=[]
        def handle(request):
            calls.append(str(request.url))
            return httpx.Response(302,headers={'Location':'https://evil.example'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            with pytest.raises(ToolError): await SupabaseFiles(Settings(supabase_url='https://project.supabase.co'),http).get('a'*32)
        assert len(calls)==1 and 'evil.example' not in calls[0]
    asyncio.run(check())


def test_uncertain_upload_with_wrong_existing_content_stops():
    def handle(request):
        return httpx.Response(409) if request.method=='POST' else httpx.Response(200,content=b'different')
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            with pytest.raises(ToolError,match='does not match'):
                await SupabaseFiles(Settings(supabase_url='https://project.supabase.co'),http).put('a'*32,b'original')
    asyncio.run(check())


def test_cloud_original_deduplication_extraction_and_restart(make_run_manager,tmp_path):
    repository=Repository(create_database(f'sqlite:///{tmp_path}/app.sqlite3'))
    setup=make_run_manager(repository=repository,settings=Settings(data_dir=tmp_path, semantic_search_enabled=True))
    files=FakeFiles()
    async def check():
        service=AgentService(setup.manager,files=files,embedder=FakeEmbeddings())
        first=await service.documents.save_async('../../notes.txt',b'API observability research')
        second=await service.documents.save_async('notes.txt',b'API observability research')
        assert first['document']['id']==second['document']['id'] and first['job']['id']==second['job']['id']
        assert files.writes==1 and not (tmp_path/'uploads').exists()
        assert await service.execute_one() and await service.execute_one()
        assert service.knowledge.status()['sources']=={'ready':1}
        setup.manager.repository.engine.dispose()
        setup.manager.repository=Repository(create_database(f'sqlite:///{tmp_path}/app.sqlite3'))
        fresh=AgentService(setup.manager,files=files,embedder=FakeEmbeddings())
        assert await fresh.documents.original(first['document']['id'])==b'API observability research'
        found=await fresh.knowledge.search('API observability')
        assert found['matches'][0]['ref'].endswith('#page=1')
        assert found['matches'][0]['purpose']=='background'
        assert setup.client.calls==[] and setup.gmail.calls==[]
    try: asyncio.run(check())
    finally: setup.manager.repository.engine.dispose()


def test_changed_original_is_rejected_before_extraction(make_run_manager):
    setup=make_run_manager(); files=FakeFiles(); service=AgentService(setup.manager,files=files)
    async def check():
        result=await service.documents.save_async('notes.txt',b'original')
        files.objects[result['document']['object_key']]=b'changed'
        with pytest.raises(ToolError,match='checksum'): await service.documents.original(result['document']['id'])
    asyncio.run(check())


def test_indexing_is_atomic_and_failed_rebuild_keeps_previous_passages(make_run_manager):
    setup=make_run_manager(settings=Settings(semantic_search_enabled=True))
    service=AgentService(setup.manager,embedder=FakeEmbeddings())
    async def check():
        source_id=source(setup.repository.engine,'Original API observability evidence.')
        await service.knowledge.index(source_id)
        first=(await service.knowledge.search('Original API observability'))['matches'][0]
        source(setup.repository.engine,'Replacement email delivery evidence.')
        class Broken(FakeEmbeddings):
            async def passages(self,texts): raise ToolError('Unavailable')
        service.knowledge.embedder=Broken()
        with pytest.raises(ToolError): await service.knowledge.index(source_id)
        found=await service.knowledge.search('Original API observability')
        assert found['matches'][0]['text']==first['text']
        service.knowledge.embedder=FakeEmbeddings()
        await service.knowledge.index(source_id)
        found=await service.knowledge.search('Replacement email delivery')
        assert found['matches'][0]['text']=='Replacement email delivery evidence.'
        await service.knowledge.index(source_id)
        with Session(setup.repository.engine) as session:
            assert session.scalar(select(func.count()).select_from(KnowledgeChunk))==1
    asyncio.run(check())


def test_keyword_fallback_and_invalid_vectors_are_explicit(make_run_manager):
    setup=make_run_manager(settings=Settings(semantic_search_enabled=True))
    class Missing(FakeEmbeddings):
        async def query(self,text): raise ToolError('Missing model')
    service=AgentService(setup.manager,embedder=Missing())
    source(setup.repository.engine)
    found=asyncio.run(service.knowledge.search('observability'))
    assert found['mode']=='keyword' and 'keyword-only' in found['warning'] and found['matches']
    for vectors in ([[1.0]],[[float('nan')]*DIMENSION],[[0.0]*DIMENSION]):
        with pytest.raises(ToolError): checked_vectors(vectors,1)


def test_browser_capture_preserves_sources_and_reuses_page_cache(make_run_manager):
    setup=make_run_manager(settings=Settings(semantic_search_enabled=True))
    service=AgentService(setup.manager,embedder=FakeEmbeddings())
    job=service.conversations.queue('Read this page','owner',[],'chat')
    page=PageEvidence(url='https://example.com/research',title='API research',text='API observability systems')
    browser=FakeBrowser({page.url:page})
    managed=ManagedBrowser(browser,setup.repository,job['run_id'],setup.manager.settings.limits)
    async def check():
        await managed.read(page.url); await managed.read(page.url)
        assert len(browser.calls)==1
        await service.knowledge.index(service.knowledge.sources()['items'][0]['id'])
        match=(await service.knowledge.search('observability'))['matches'][0]
        assert match['ref']==page.url and match['purpose']=='research'
    asyncio.run(check())


def test_telegram_conversation_uses_saved_knowledge_from_an_earlier_task(make_run_manager):
    settings=Settings(semantic_search_enabled=True,telegram_owner_id=123)
    setup=make_run_manager(settings=settings,responses=[
        {'action':'search_saved','query':'API observability'},
        {'action':'reply','text':'Your saved notes cover API observability.','sources':['document:'+'a'*32+'#page=2']}])
    service=AgentService(setup.manager,embedder=FakeEmbeddings())
    async def check():
        source_id=source(setup.repository.engine,ref='document:'+'a'*32,kind='document')
        await service.knowledge.index(source_id)
        # No file attached to this later task; owner library access is explicit.
        job=service.conversations.queue('What was in my earlier notes?','new-conversation',[],'new-turn')
        while await service.execute_one(): pass
        saved=service.store.get('chat:result:'+job['run_id'])
        assert 'Sources:' in saved['text'] and 'Example source, page 2' in saved['text']
        assert 'a'*32 not in saved['text']
        prompt=json.loads(setup.client.calls[-1].input_text)
        assert prompt['observations'][0]['tool']=='search_saved'
        assert prompt['observations'][0]['passages'][0]['purpose']=='background'
        assert prompt['observations'][0]['passages'][0]['ref']=='document:'+'a'*32+'#page=2'
        assert setup.gmail.calls==[]
    asyncio.run(check())


def test_native_saved_search_is_only_advertised_when_enabled():
    assert 'search_saved' not in {t['name'] for t in tool_definitions({'tools_allowed':True,'capabilities':{}})}
    assert 'search_saved' in {t['name'] for t in tool_definitions({'tools_allowed':True,'capabilities':{'knowledge':True}})}
    with pytest.raises(ModelResponseError):
        checked_call({'name':'search_saved','call_id':'x','arguments':'{"query":"find notes"}'},{'run_status'})


def test_validation_cleans_up_all_probe_data_without_model_calls(make_run_manager):
    setup=make_run_manager(settings=Settings(semantic_search_enabled=True))
    files=FakeFiles(); service=AgentService(setup.manager,files=files,embedder=FakeEmbeddings())
    report=asyncio.run(validate_storage(service))
    assert report['status']=='passed',report
    assert files.objects=={} and service.knowledge.status()['passages']==0
    assert service.store.jobs()==[] and setup.client.calls==[] and setup.gmail.calls==[]
    async def checkpoints(): return [item async for item in setup.manager.checkpointer.alist(None)]
    assert asyncio.run(checkpoints())==[]


def test_dashboard_knowledge_download_and_validation_require_owner_login(make_run_manager,tmp_path):
    setup=make_run_manager(settings=Settings(data_dir=tmp_path,owner_password='password',semantic_search_enabled=True))
    with TestClient(create_app(manager=setup.manager,background=False)) as client:
        for route in ('/api/knowledge/search','/api/storage/validate'):
            assert client.post(route,json={'query':'test'}).status_code==401
        assert client.get('/api/documents/'+'a'*32+'/original').status_code==401
        csrf=client.post('/auth/login',json={'password':'password'}).json()['csrf']
        assert client.post('/api/storage/validate').status_code==403
        client.headers['X-CSRF-Token']=csrf
        service=client.app.state.service
        service.knowledge.embedder=FakeEmbeddings()
        saved=client.post('/api/documents?filename=notes.txt',content=b'API observability').json()
        client.portal.call(service.execute_one); client.portal.call(service.execute_one)
        document_id=saved['document']['id']
        downloaded=client.get(f'/api/documents/{document_id}/original')
        assert downloaded.status_code==200 and downloaded.content==b'API observability'
        assert 'attachment' in downloaded.headers['content-disposition']
        found=client.post('/api/knowledge/search',json={'query':'observability'})
        assert found.status_code==200 and found.json()['matches']
        assert client.post('/api/knowledge/search',json={'query':' '}).status_code==422
        source_id=found.json()['matches'][0]['source_id']
        assert client.post(f'/api/knowledge/sources/{source_id}/reindex').status_code==202
        client.portal.call(service.execute_one)
        assert client.post('/api/storage/validate').status_code==202
        client.portal.call(service.execute_one)
        assert client.get('/api/connectors').json()['storage']['validation']['status']=='passed'


def test_fresh_start_backup_preserves_local_records_and_telegram_cursor(tmp_path):
    engine=create_database(f'sqlite:///{tmp_path}/relationships.sqlite3')
    store=ControlStore(engine)
    store.put('telegram_offset',{'next':42})
    store.put('private:test',{'value':'kept locally'})
    engine.dispose()
    folder,cursor=backup_local(tmp_path)
    assert cursor=={'next':42}
    backup=create_database(f'sqlite:///{folder}/relationships.sqlite3')
    try: assert ControlStore(backup).get('private:test')=={'value':'kept locally'}
    finally: backup.dispose()


def test_real_postgres_pgvector_search_and_restart(postgres_url,tmp_path):
    settings=Settings(supabase_database_url=postgres_url,semantic_search_enabled=True)
    engine=create_database(settings.database_url,private_schema=True)
    async def check():
        service=KnowledgeService(engine,settings,FakeEmbeddings())
        source_id=source(engine)
        await service.index(source_id)
        found=await service.search('API observability')
        assert found['mode']=='hybrid' and found['matches'][0]['source_id']==source_id
        with engine.connect() as connection:
            assert connection.execute(text("SELECT extname FROM pg_extension WHERE extname='vector'")).scalar()=='vector'
            indexes=connection.execute(text("SELECT indexname FROM pg_indexes WHERE schemaname='outreach'")).scalars().all()
            assert 'ix_knowledge_vector' in indexes and 'ix_knowledge_keywords' in indexes
        engine.dispose()
        reopened=create_database(settings.database_url,private_schema=True)
        try:
            fresh=KnowledgeService(reopened,settings,FakeEmbeddings())
            assert (await fresh.search('API observability'))['matches'][0]['ref']=='https://example.com/research'
        finally: reopened.dispose()
    try: asyncio.run(check())
    finally: engine.dispose()


def test_stopped_saved_search_resumes_from_postgres_without_querying_again(postgres_url,tmp_path):
    from app.llm.client import FakeModelClient
    settings=Settings(supabase_database_url=postgres_url,data_dir=tmp_path,semantic_search_enabled=True)
    first=FakeModelClient([{'action':'search_saved','query':'API observability'}])
    second=FakeModelClient([{'action':'reply','text':'Recovered the saved passage.'}])
    class Counted(FakeEmbeddings):
        queries=0
        async def query(self,value):
            self.queries+=1
            return await super().query(value)
    @asynccontextmanager
    async def client(value): yield value
    async def check():
        async with open_runtime(settings) as manager:
            manager.client_factory=lambda: client(first)
            embedder=Counted(); service=AgentService(manager,embedder=embedder)
            source_id=source(manager.repository.engine)
            await service.knowledge.index(source_id)
            job=service.conversations.queue('Find earlier API notes','owner',[],'turn')
            original=service.knowledge.search
            async def stop_after_search(value):
                result=await original(value)
                service.tasks.stop(job['run_id'])
                return result
            service.knowledge.search=stop_after_search
            while await service.execute_one(): pass
            assert manager.repository.run(job['run_id'])['status']=='stopped'
            assert embedder.queries==1
        async with open_runtime(settings) as manager:
            manager.client_factory=lambda: client(second)
            embedder=Counted(); service=AgentService(manager,embedder=embedder)
            resumed=await service.tasks.continue_task('owner','continue',job['run_id'])
            assert resumed['run_id']==job['run_id']
            while await service.execute_one(): pass
            assert manager.repository.run(job['run_id'])['status']=='completed'
            assert manager.repository.run(job['run_id'])['model_calls']==2
            assert embedder.queries==0
            assert service.store.get('chat:result:'+job['run_id'])['evidence'][0]['tool']=='search_saved'
        assert len(first.calls)==1 and len(second.calls)==1
    asyncio.run(check())


def test_retrieved_background_is_excluded_from_outreach_prospect_evidence(make_run_manager,workflow_data):
    from app.agent.conversation import ConversationContext
    setup=make_run_manager(settings=Settings(semantic_search_enabled=True))
    service=AgentService(setup.manager,embedder=FakeEmbeddings())
    job=service.conversations.queue('Create requested email drafts','owner',[],'turn')
    context=ConversationContext(service.conversations,job['run_id'],setup.client,None,None,
        {'sender_profile':workflow_data.request.sender.model_dump(), 'attached_files':[], 'previous_evidence':[]},setup.manager.settings.limits)
    passages=[{'ref':'document:'+'a'*32+'#page=1','label':'Private CV','purpose':'background','text':'PRIVATE EXPERIENCE'},
              {'ref':'https://example.com/research','label':'Public study','purpose':'research','text':'PUBLIC EVIDENCE'}]
    observation={'tool':'search_saved','passages':passages,'sources':[{'ref':p['ref'],'label':p['label']} for p in passages],
                 'content':json.dumps(passages)}
    answer=service.conversations.response(ConversationAction(action='outreach',request=workflow_data.request),[observation],context)
    material=answer['proposal']['research_material']
    assert 'PUBLIC EVIDENCE' in material and 'PRIVATE EXPERIENCE' not in material


def test_validation_reports_cleanup_failures_without_credentials(make_run_manager):
    setup=make_run_manager(settings=Settings(semantic_search_enabled=True))
    class BrokenFiles(FakeFiles):
        async def delete(self,key): raise RuntimeError('private-database-password')
    service=AgentService(setup.manager,files=BrokenFiles(),embedder=FakeEmbeddings())
    report=asyncio.run(validate_storage(service))
    assert report['status']=='failed' and report['checks'][-1]['status']=='failed'
    assert 'private-database-password' not in json.dumps(report)
