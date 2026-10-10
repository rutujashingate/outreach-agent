"""Files become cited research inputs without credentials or external services."""
import asyncio
from copy import deepcopy
from io import BytesIO
import json
import os
import shutil
import zipfile

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy.orm import Session

from app.connectors.documents.extractor import extract, ExtractionError
from app.connectors.telegram.client import TelegramClient, FakeTelegram
from app.connectors.telegram.bot import TelegramBot
from app.connectors.search import FakeSearchTool, ToolError
from app.domain.documents import MAX_FILE_BYTES
from app.domain.workflow import WorkflowRequest
from app.main import create_app
from app.services.application import AgentService
from app.services.documents import DocumentService
from app.settings import Settings
from app.storage.documents import DocumentRow
from app.storage.control import ControlStore


def text_pdf(texts):
    """Make a small genuine PDF fixture without another PDF-writing dependency."""
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
        ('<< /Type /Pages /Count %d /Kids [%s] >>' % (len(texts), ' '.join(f'{4+2*i} 0 R' for i in range(len(texts))))).encode(),
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    for i, text in enumerate(texts):
        escaped = text.replace('\\','\\\\').replace('(','\\(').replace(')','\\)')
        stream = f'BT /F1 16 Tf 50 740 Td ({escaped}) Tj ET'.encode()
        objects.extend([f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents {5+2*i} 0 R >>'.encode(),
                        f'<< /Length {len(stream)} >>\nstream\n'.encode()+stream+b'\nendstream'])
    output=bytearray(b'%PDF-1.4\n'); offsets=[0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(output)); output.extend(f'{i} 0 obj\n'.encode()+obj+b'\nendobj\n')
    xref=len(output); output.extend(f'xref\n0 {len(offsets)}\n0000000000 65535 f \n'.encode())
    for offset in offsets[1:]: output.extend(f'{offset:010} 00000 n \n'.encode())
    output.extend(f'trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF'.encode())
    return bytes(output)


def image_bytes(kind='PNG'):
    image=Image.new('RGB',(1100,260),'white')
    ImageDraw.Draw(image).multiline_text((35,40),'Example AI research\nAPI observability systems',fill='black',font=ImageFont.load_default(size=42),spacing=18)
    output=BytesIO(); image.save(output,format=kind); return output.getvalue()


@pytest.mark.parametrize('suffix', ['.txt','.md','.csv','.json','.log','.yaml','.xml'])
def test_plain_text_formats_keep_evidence(suffix):
    result=extract('Example AI — observability'.encode(),suffix)
    assert result.pages[0].text=='Example AI — observability'
    assert result.pages[0].method=='text'


def test_html_reads_text_without_executing_or_keeping_scripts():
    result=extract(b'<head><title>Hidden</title><script>secret()</script></head><p>Example AI</p><p>Public research</p>','.html')
    assert 'Example AI' in result.pages[0].text and 'secret' not in result.pages[0].text


@pytest.mark.parametrize('suffix,member,xml', [
    ('.docx','word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Example AI</w:t></w:r></w:p></w:body></w:document>'),
    ('.odt','content.xml','<root xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"><text:p>Example AI</text:p></root>')])
def test_office_documents_read_only_text(suffix,member,xml):
    data=BytesIO()
    with zipfile.ZipFile(data,'w') as archive: archive.writestr(member,xml)
    assert extract(data.getvalue(),suffix).pages[0].text=='Example AI'


def test_pdf_keeps_real_page_numbers_and_rejects_too_many_pages():
    result=extract(text_pdf(['Example AI sources','API observability work']),'.pdf')
    assert [p.number for p in result.pages]==[1,2]
    assert result.pages[1].text=='API observability work'
    with pytest.raises(ExtractionError,match='20 pages'): extract(text_pdf(['page']*21),'.pdf')


@pytest.mark.parametrize('data,suffix', [(b'\x00\x01binary','.txt'),(b'not PDF','.pdf'),(b'invalid','.docx'),(b'#!/bin/sh','.sh'),(b'', '.txt')])
def test_malformed_binary_empty_and_unsupported_files_are_rejected(data,suffix):
    with pytest.raises(ExtractionError): extract(data,suffix)


def test_truncation_is_visible_and_missing_ocr_is_actionable(monkeypatch):
    result=extract(b'A'*45000,'.txt')
    assert len(result.pages[0].text)==40000 and result.warnings
    monkeypatch.setattr(shutil,'which',lambda name:None)
    with pytest.raises(ExtractionError,match='Install Tesseract'): extract(image_bytes(),'.png')


@pytest.mark.skipif(os.getenv('RUN_OCR_TESTS')!='1',reason='Opt into installed Tesseract checks')
@pytest.mark.parametrize('kind,suffix',[('PNG','.png'),('PDF','.pdf')])
def test_real_ocr_reads_images_and_scanned_pdf_pages(kind,suffix):
    result=extract(image_bytes(kind),suffix)
    assert 'Example' in result.pages[0].text and 'observability' in result.pages[0].text
    assert result.pages[0].method=='ocr'


def test_upload_deduplication_restart_and_subprocess_extraction(make_run_manager,tmp_path):
    setup=make_run_manager(settings=Settings(data_dir=tmp_path,checkpoint_backend='memory'))
    service=AgentService(setup.manager)
    first=service.documents.save('../../research.txt',b'Example AI research')
    second=service.documents.save('research.txt',b'Example AI research')
    assert first['document']['id']==second['document']['id'] and first['job']['id']==second['job']['id']
    assert first['document']['filename']=='research.txt'
    fresh=AgentService(setup.manager)
    assert asyncio.run(fresh.execute_one())
    record=fresh.documents.get(first['document']['id'])
    assert record['status']=='ready' and record['content']['pages'][0]['text']=='Example AI research'
    assert setup.client.calls==[]


def test_unicode_worker_output_is_not_lost_between_pipe_chunks(make_run_manager,tmp_path):
    setup=make_run_manager(settings=Settings(data_dir=tmp_path))
    service=AgentService(setup.manager)
    text='資料についての研究🙂\n'*3500
    saved=service.documents.save('research.txt',text.encode())
    asyncio.run(service.execute_one())
    record=service.documents.get(saved['document']['id'])
    assert record['status']=='ready'
    assert record['content']['pages'][0]['text']==text.strip()[:40000]


def test_evidence_limits_keep_every_source_and_valid_json():
    from app.agent.nodes.documents import bounded_evidence
    records=[{'filename':'"'*180, 'purpose':'research', 'source':f'document:{i//20:032x}#page={i%20+1}',
              'text':'"\\🙂'*10000} for i in range(100)]
    material,clipped=bounded_evidence(records,39999,20000)
    result=json.loads(material)['uploaded_documents']
    assert clipped and len(material)<=39999
    assert len(result)==100 and all(item['text'] for item in result)
    assert [item['source'] for item in result]==[item['source'] for item in records]


def test_background_is_sender_context_and_documents_survive_checkpoints(make_run_manager,tmp_path):
    from types import SimpleNamespace
    from app.agent.nodes.documents import prepare_documents
    from app.domain.workflow import WorkflowState
    from app.storage.checkpoints import checkpoint_serializer
    setup=make_run_manager(settings=Settings(data_dir=tmp_path))
    service=AgentService(setup.manager)
    saved=service.documents.save('profile.txt',b'I build API observability tools.')
    asyncio.run(service.execute_one())
    state=WorkflowState(run_id='background-test',goal='Find relevant research groups',
                        attachments=[{'document_id':saved['document']['id'],'purpose':'background'}])
    result=asyncio.run(prepare_documents(state,SimpleNamespace(context=SimpleNamespace(repository=setup.manager.repository))))
    assert 'API observability' in result['sender'].context
    assert state.research_material=='' and state.sender.context==''
    serializer=checkpoint_serializer()
    restored=serializer.loads_typed(serializer.dumps_typed(result['documents']))
    assert restored==result['documents'] and restored[0].purpose=='background'


def test_cancelled_parser_marks_file_failed_and_kills_process_group(make_run_manager,tmp_path,monkeypatch):
    from types import SimpleNamespace
    import app.services.documents as documents
    setup=make_run_manager(settings=Settings(data_dir=tmp_path))
    service=AgentService(setup.manager)
    saved=service.documents.save('notes.txt',b'Example AI')
    killed=[]
    async def cancelled_read(size): raise asyncio.CancelledError()
    async def wait(): return 0
    async def start(*args,**kwargs):
        assert 'GROQ_API_KEY' not in kwargs['env']
        return SimpleNamespace(stdout=SimpleNamespace(read=cancelled_read),returncode=None,pid=424242,wait=wait)
    monkeypatch.setenv('GROQ_API_KEY','must-not-reach-parser')
    monkeypatch.setattr(documents.asyncio,'create_subprocess_exec',start)
    monkeypatch.setattr(documents.os,'killpg',lambda pid,sig:killed.append(pid))
    with pytest.raises(asyncio.CancelledError): asyncio.run(service.documents.extract(saved['document']['id']))
    assert killed==[424242] and service.documents.get(saved['document']['id'])['status']=='failed'


def test_interrupted_file_can_be_explicitly_retried(make_run_manager,tmp_path):
    setup=make_run_manager(settings=Settings(data_dir=tmp_path))
    service=AgentService(setup.manager)
    saved=service.documents.save('paper.txt',b'Example research')
    service.store.claim();service.store.recover();service.documents.recover()
    assert service.documents.get(saved['document']['id'])['status']=='failed'
    service.documents.retry(saved['document']['id'],'retry-file')
    asyncio.run(service.execute_one())
    assert service.documents.get(saved['document']['id'])['status']=='ready'


def test_file_evidence_guides_the_goal_search_and_source_validation(make_run_manager,workflow_data,tmp_path):
    search=FakeSearchTool([])
    responses=deepcopy(workflow_data.responses)
    responses[0]['research_signals']=['API observability']
    setup=make_run_manager(responses=responses,search=search,settings=Settings(data_dir=tmp_path))
    service=AgentService(setup.manager)
    saved=service.documents.save('research.txt',b'Example AI and Example Contact hire platform engineers and study API observability. https://example.com/careers')
    asyncio.run(service.execute_one())
    source=f"document:{saved['document']['id']}#page=1"
    # The shared fake client keeps the supplied response objects.
    responses[1]['prospects'][0]['sources']=[source]
    # Replace the fake client after preparing the precise document citation.
    from app.llm.client import FakeModelClient
    from contextlib import asynccontextmanager
    client=FakeModelClient(responses)
    @asynccontextmanager
    async def factory(): yield client
    setup.manager.client_factory=factory
    request=WorkflowRequest.model_validate({**workflow_data.request.model_dump(), 'research_material':'','use_search':True,
        'attachments':[{'document_id':saved['document']['id'],'purpose':'research'}]})
    job=service.start(request,'start');asyncio.run(service.execute_one())
    result=service.state(job['run_id'])
    assert result.awaiting_approval, result.error
    assert source in result.state.prospects[0].sources
    assert 'API observability' in str(search.queries)
    assert 'Example AI' in client.calls[0].input_text
    assert result.state.documents[0].filename=='research.txt'


def test_private_document_email_requires_owner_selection(make_run_manager,workflow_data,tmp_path):
    from app.domain.documents import DocumentEvidence,DocumentPage
    from app.agent.nodes.recipients import prepare_recipients
    from app.domain.workflow import WorkflowState
    from types import SimpleNamespace
    state=WorkflowState(run_id='test',goal='Find AI startups',discover_emails=True)
    prospect=deepcopy(workflow_data.responses[1]['prospects'][0])
    prospect['sources']=['document:'+'a'*32+'#page=1']
    from app.domain.schemas import Prospect
    state.qualified_prospects=[Prospect.model_validate(prospect)]
    state.documents=[DocumentEvidence(document_id='a'*32,filename='list.txt',purpose='research',sha256='x',
        pages=[DocumentPage(number=1,text='Example AI contact@example.com')])]
    result=asyncio.run(prepare_recipients(state,SimpleNamespace()))
    assert result['recipient_requests']==['p1']
    assert result['recipient_candidates']['p1'][0].email=='contact@example.com'


def test_authenticated_upload_rejects_oversize_and_unknown_documents(make_run_manager,tmp_path):
    setup=make_run_manager(settings=Settings(data_dir=tmp_path,api_key='key'))
    with TestClient(create_app(manager=setup.manager,background=False)) as client:
        assert client.post('/api/documents?filename=notes.txt',content=b'private notes').status_code==401
        headers={'X-API-Key':'key'}
        made=client.post('/api/documents?filename=notes.txt',content=b'Example AI',headers=headers)
        assert made.status_code==202 and made.json()['document']['status']=='queued'
        client.portal.call(client.app.state.service.execute_one)
        document_id=made.json()['document']['id']
        assert client.get('/api/documents/'+document_id,headers=headers).json()['status']=='ready'
        assert client.get('/api/documents/'+document_id).status_code==401
        assert client.post('/api/documents?filename=large.txt',content=b'x'*(MAX_FILE_BYTES+1),headers=headers).status_code==413
        assert client.post('/api/runs',json={'goal':'Search','attachments':[{'document_id':'a'*32}]},headers=headers).status_code==404


def test_telegram_attachments_survive_handler_restart_and_ignore_unauthorized_updates(make_run_manager,tmp_path):
    setup=make_run_manager(settings=Settings(data_dir=tmp_path,telegram_owner_id=123))
    service=AgentService(setup.manager);client=FakeTelegram();client.files['file']=b'Example AI sources'
    bot=TelegramBot(service,client)
    def message(update_id, owner=123):
        return {'update_id':update_id,'message':{'from':{'id':owner},'chat':{'id':owner,'type':'private'},
            'document':{'file_id':'file','file_name':'notes.txt','file_size':18},'caption':'Find AI startups'}}
    async def run():
        service.store.accept_updates([message(1,999)],123);assert not await bot.process_one();assert client.calls==[]
        service.store.accept_updates([message(2),message(2)],123);assert await bot.process_one()
        fresh=TelegramBot(AgentService(setup.manager),client)
        assert not await fresh.process_one()
        conversation=service.store.get('telegram_conversation')
        assert conversation['stage']=='chat' and len(conversation['request']['attachments'])==1
        assert len([c for c in client.calls if c[0]=='download'])==1
        await service.execute_one()
        assert service.documents.get(conversation['request']['attachments'][0]['document_id'])['status']=='ready'
    asyncio.run(run())


def test_telegram_download_bounds_bytes_and_redacts_token():
    calls=[]
    def transport(request):
        calls.append(request)
        if request.url.path.endswith('getFile'): return httpx.Response(200,json={'ok':True,'result':{'file_path':'documents/file.txt'}})
        return httpx.Response(200,content=b'oversized file data')
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
            with pytest.raises(ToolError) as error: await TelegramClient(http,'private-token').download_file('id',5)
            assert 'private-token' not in str(error.value)
    asyncio.run(run())
