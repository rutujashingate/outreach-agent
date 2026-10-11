"""Authenticated dashboard API; all work delegates to AgentService."""
from typing import Annotated
from uuid import uuid4
import os

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from app.services.auth import require_owner
from app.domain.workflow import ApprovalDecision, ApprovalSubmission, WorkflowRequest, Recipient, Sender

router = APIRouter(prefix='/api', dependencies=[Depends(require_owner)])


def service(request): return request.app.state.service

def request_key(value):
    if value is not None and (not 1 <= len(value) <= 100 or not value.isascii()):
        raise ValueError('Idempotency-Key must contain 1–100 ASCII characters.')
    return 'web:' + (value or uuid4().hex)


class Selections(BaseModel):
    model_config = ConfigDict(extra='forbid')
    recipients: dict[str, Recipient | None]


class QueueSetting(BaseModel):
    model_config = ConfigDict(extra='forbid')
    paused: bool = Field(strict=True)


class DemoMessage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(default='', max_length=10000)
    callback_data: str | None = Field(default=None, max_length=64)


def connections(request):
    from app.llm.xai_routing import configured_models
    manager = service(request).manager
    settings = manager.settings
    model_key = {'groq': 'GROQ_API_KEY', 'openai': 'OPENAI_API_KEY', 'xai': 'XAI_API_KEY'}[settings.model_provider]
    gmail = manager.gmail.status() if manager.gmail and hasattr(manager.gmail, 'status') else {'connected': False}
    return {'gmail': gmail, 'telegram': service(request).store.get('telegram_status', {'health': 'disabled'}),
            'storage': {'database': 'supabase' if settings.supabase_database_url else manager.repository.engine.dialect.name,
                        'checkpoints': settings.checkpoint_backend, 'schema': 'outreach' if settings.supabase_database_url else None},
            'browser': {'available': manager.browser is not None}, 'search': {'configured': manager.search is not None},
            'documents': service(request).documents.status(),
            'model': {'provider': settings.model_provider, 'configured': settings.demo or bool(os.getenv(model_key, '').strip())}, 'demo': settings.demo,
            'model_routes': configured_models() if settings.model_provider == 'xai' and settings.xai_task_routing and not settings.demo else {},
            'sender_profile': service(request).store.get('sender_profile', {'name': 'User', 'context': ''})}


@router.get('/overview')
async def overview(request: Request): return {**service(request).overview(), 'connections': connections(request)}


@router.get('/runs')
async def list_runs(request: Request, page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100)):
    return service(request).list_runs(page=page, limit=limit)


@router.post('/runs', status_code=202)
async def start_run(request: Request, body: WorkflowRequest, idempotency_key: Annotated[str | None, Header()] = None):
    return service(request).start(body, request_key(idempotency_key))


@router.get('/runs/{run_id}')
async def run_details(request: Request, run_id: str, event_page: int = Query(1, ge=1)):
    return service(request).details(run_id, event_page=event_page)


@router.post('/runs/{run_id}/choices')
async def stage_decision(request: Request, run_id: str, body: ApprovalDecision):
    return service(request).stage_decision(run_id, body)


@router.post('/runs/{run_id}/decisions', status_code=202)
async def decisions(request: Request, run_id: str, body: ApprovalSubmission, idempotency_key: Annotated[str | None, Header()] = None):
    return service(request).decisions(run_id, body, request_key(idempotency_key))


@router.post('/runs/{run_id}/submit', status_code=202)
async def submit(request: Request, run_id: str, idempotency_key: Annotated[str | None, Header()] = None):
    return service(request).submit_choices(run_id, request_key(idempotency_key))


@router.post('/runs/{run_id}/recipients', status_code=202)
async def recipients(request: Request, run_id: str, body: Selections, idempotency_key: Annotated[str | None, Header()] = None):
    return service(request).select_recipients(run_id, {k: v.model_dump() if v else None for k,v in body.recipients.items()}, request_key(idempotency_key))


@router.post('/runs/{run_id}/retry', status_code=202)
async def retry(request: Request, run_id: str, idempotency_key: Annotated[str | None, Header()] = None):
    return service(request).retry(run_id, request_key(idempotency_key))


@router.post('/runs/{run_id}/cancel', status_code=202)
async def cancel(request: Request, run_id: str): return service(request).cancel(run_id)


@router.post('/runs/{run_id}/stop', status_code=202)
async def stop(request: Request, run_id: str): return service(request).tasks.stop(run_id)


@router.post('/runs/{run_id}/continue', status_code=202)
async def continue_run(request: Request, run_id: str, idempotency_key: Annotated[str | None, Header()] = None):
    return await service(request).tasks.continue_task('', request_key(idempotency_key), run_id)


@router.put('/queue')
async def queue(request: Request, body: QueueSetting):
    service(request).store.put('queue', body.model_dump()); return body


@router.put('/profile')
async def profile(request: Request, body: Sender):
    service(request).store.put('sender_profile', body.model_dump()); return body


@router.post('/replies/check', status_code=202)
async def check_replies(request: Request, idempotency_key: Annotated[str | None, Header()] = None):
    return service(request).queue_replies(request_key(idempotency_key))


@router.get('/connectors')
async def connectors(request: Request): return connections(request)


def gmail_account(request):
    account = getattr(service(request).manager.gmail, 'account', None)
    if account is None: raise HTTPException(409, 'Gmail sign-in is unavailable in this runtime.')
    return account


@router.post('/connectors/gmail/connect')
async def connect_gmail(request: Request):
    session_id, _ = request.app.state.auth.session(request)
    return {'url': gmail_account(request).connect_url(session_id)}


@router.get('/connectors/gmail/callback')
async def gmail_callback(request: Request, state: str = '', code: str = '', error: str = ''):
    if error or not state or not code: return RedirectResponse('/?gmail=cancelled', status_code=303)
    session_id, _ = request.app.state.auth.session(request)
    await gmail_account(request).complete(state, code, session_id)
    return RedirectResponse('/?gmail=connected', status_code=303)


@router.post('/connectors/gmail/disconnect')
async def disconnect_gmail(request: Request): return await gmail_account(request).disconnect()


@router.post('/demo/telegram')
async def demo_telegram(request: Request, body: DemoMessage):
    if not request.app.state.settings.demo: raise HTTPException(404)
    bot = request.app.state.bot
    current = service(request).store.get('demo_update', {}).get('value', 0) + 1
    service(request).store.put('demo_update', {'value': current})
    message = {'chat': {'id': bot.owner, 'type': 'private'}, 'from': {'id': bot.owner}, 'text': body.text}
    update = {'update_id': current, 'message': message}
    if body.callback_data:
        update = {'update_id': current, 'callback_query': {'id': str(current), 'from': {'id': bot.owner}, 'message': message, 'data': body.callback_data}}
    bot.store.accept_updates([update], bot.owner)
    await bot.process_one()
    while await bot.deliver_one(): pass
    return {'messages': [payload for method, payload in bot.client.calls if method == 'sendMessage'][-30:]}


@router.post('/documents', status_code=202)
async def upload_document(request: Request, filename: str = Query(min_length=1, max_length=180)):
    """Stream one raw file after owner authentication, with a hard size ceiling."""
    import asyncio
    from app.domain.documents import MAX_FILE_BYTES
    data = bytearray()
    try:
        async with asyncio.timeout(30):
            async for chunk in request.stream():
                if len(data) + len(chunk) > MAX_FILE_BYTES:
                    raise HTTPException(413, 'Files may be at most 10 MiB.')
                data.extend(chunk)
    except TimeoutError:
        raise HTTPException(408, 'The upload took too long. Try again.') from None
    return service(request).documents.save(filename, bytes(data))


@router.get('/documents')
async def documents(request: Request, page: int = Query(1, ge=1), ids: str = Query('', max_length=164)):
    if ids:
        values = ids.split(',')
        if len(values) > 5: raise ValueError('At most five document IDs.')
        return {'page': 1, 'items': [{k:v for k,v in service(request).documents.get(value).items() if k != 'content'} for value in values]}
    return service(request).documents.list(page)


@router.get('/documents/{document_id}')
async def document_details(request: Request, document_id: str):
    return service(request).documents.get(document_id)


@router.post('/documents/{document_id}/retry', status_code=202)
async def retry_document(request: Request, document_id: str, idempotency_key: Annotated[str | None, Header()] = None):
    return service(request).documents.retry(document_id, request_key(idempotency_key))
