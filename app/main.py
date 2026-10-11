"""Start one service for Telegram, the dashboard, and the shared job worker."""
import argparse
import asyncio
from collections import deque
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
import time
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.settings import Settings
from app.services.application import AgentService
from app.services.auth import OwnerAuth, require_owner
from app.services.instance import instance_lock
from app.services.runtime import open_runtime
from app.services.runs import ConfigurationError, RunConflict, RunNotFound
from app.services.limits import LimitExceeded
from app.connectors.search import ToolError
from app.connectors.telegram.client import TelegramClient, FakeTelegram
from app.connectors.telegram.bot import TelegramBot
from app.web.routes.control import router

STATIC = Path(__file__).parent / 'web' / 'static'


class Login(BaseModel):
    password: str = Field(max_length=1024)


def create_app(*, settings=None, manager=None, background=True):
    configured = settings or (manager.settings if manager else Settings.from_env())

    @asynccontextmanager
    async def lifespan(application):
        if not configured.owner_password and not configured.api_key and not configured.demo:
            raise RuntimeError('Set OUTREACH_OWNER_PASSWORD before starting the service.')
        if configured.telegram_token and configured.telegram_owner_id <= 0:
            raise RuntimeError('Set OUTREACH_TELEGRAM_OWNER_ID to your numeric Telegram user ID.')
        async with AsyncExitStack() as stack:
            if manager is None: stack.enter_context(instance_lock(configured.data_dir))
            ready = manager or await stack.enter_async_context(open_runtime(configured))
            application.state.settings = configured
            application.state.service = service = AgentService(ready)
            application.state.auth = OwnerAuth(service.store, configured.owner_password or ('demo' if configured.demo else ''))
            application.state.window = deque()
            if manager is None:
                service.store.recover()
                service.documents.recover()
                service.knowledge.recover()
            http = await stack.enter_async_context(httpx.AsyncClient(timeout=30))
            client = FakeTelegram() if configured.demo else TelegramClient(http, configured.telegram_token)
            bot = TelegramBot(service, client); application.state.bot = bot
            tasks = []
            if background:
                tasks.append(asyncio.create_task(service.worker(), name='outreach-worker'))
                if configured.telegram_token and not configured.demo:
                    tasks += [asyncio.create_task(bot.poll(), name='telegram-poller'), asyncio.create_task(bot.handle(), name='telegram-handler')]
            application.state.tasks = tasks
            try: yield
            finally:
                service.stopping.set(); bot.stop.set()
                # Stop accepting work, then allow an in-flight bounded Gmail
                # request to record its result before cancelling the worker.
                if tasks:
                    done, pending = await asyncio.wait(tasks, timeout=configured.limits.tool_timeout + 2)
                    for task in pending: task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)

    application = FastAPI(title='Outreach Agent', version='0.3.0', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    application.add_middleware(TrustedHostMiddleware, allowed_hosts=list({urlsplit(configured.app_url).hostname or 'localhost', 'localhost', '127.0.0.1'} | ({'testserver'} if manager else set())))
    application.include_router(router)
    application.mount('/static', StaticFiles(directory=STATIC, check_dir=False), name='static')

    @application.middleware('http')
    async def headers_and_limits(request, call_next):
        if request.url.path.startswith('/api/') and hasattr(application.state, 'window'):
            window = application.state.window
            moment = time.monotonic()
            while window and window[0] < moment - 60: window.popleft()
            if len(window) >= configured.limits.max_requests_per_minute:
                return JSONResponse({'detail': 'Request limit reached. Try again shortly.'}, status_code=429)
            window.append(moment)
        response = await call_next(request)
        response.headers.update({'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer',
            'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'",
            'Cache-Control': 'no-store'})
        return response

    @application.get('/')
    async def dashboard(): return FileResponse(STATIC / 'index.html')

    @application.get('/health')
    async def health():
        tasks = application.state.tasks
        healthy = not any(task.done() for task in tasks)
        return JSONResponse({'status': 'ok' if healthy else 'degraded'}, status_code=200 if healthy else 503)

    @application.post('/auth/login')
    async def login(body: Login, request: Request):
        token, csrf = application.state.auth.login(body.password, request.client.host if request.client else 'local')
        response = JSONResponse({'csrf': csrf, 'demo': configured.demo})
        response.set_cookie('outreach_session', token, httponly=True, secure=configured.app_url.startswith('https://'), samesite='lax', max_age=43200)
        return response

    @application.get('/auth/session')
    async def session(request: Request):
        _, saved = application.state.auth.session(request)
        return {'csrf': saved['csrf'], 'demo': configured.demo}

    @application.post('/auth/logout')
    async def logout(request: Request):
        session_id = await require_owner(request)
        application.state.service.store.delete('session:' + session_id)
        response = JSONResponse({'signed_out': True}); response.delete_cookie('outreach_session'); return response

    @application.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        # Validation errors must not echo passwords or credential-bearing input.
        return JSONResponse({'detail': [{k: e[k] for k in ('loc', 'msg', 'type')} for e in error.errors()]}, status_code=422)

    async def known_error(request, error):
        code = 409 if isinstance(error, RunConflict) else 404 if isinstance(error, RunNotFound) else 503 if isinstance(error, ConfigurationError) else 429 if isinstance(error, LimitExceeded) else 502 if isinstance(error, ToolError) else 422
        message = str(error) if isinstance(error, (RunConflict, RunNotFound, ConfigurationError, LimitExceeded, ToolError)) else 'The supplied data is invalid.'
        return JSONResponse({'detail': message}, status_code=code)
    for error in (RunConflict, RunNotFound, ConfigurationError, LimitExceeded, ToolError, ValueError):
        application.add_exception_handler(error, known_error)
    return application


def main():
    from dotenv import load_dotenv
    import uvicorn
    load_dotenv(Path.cwd() / '.env', override=False)
    parser = argparse.ArgumentParser(description='Start the Telegram outreach service and dashboard.')
    parser.add_argument('--demo', action='store_true', help='Use fictional data and fake connectors.')
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.demo or settings.demo:
        settings = settings.model_copy(update={'demo': True, 'data_dir': settings.data_dir / 'demo', 'database_url': None, 'supabase_database_url': None,
            'checkpoint_backend': 'sqlite', 'telegram_token': '', 'telegram_owner_id': 1, 'owner_password': settings.owner_password or 'demo'})
    import os
    uvicorn.run(create_app(settings=settings), host=os.getenv('OUTREACH_HOST', '127.0.0.1'), port=int(os.getenv('OUTREACH_PORT', '8000')),
                access_log=False, timeout_graceful_shutdown=30)


if __name__ == '__main__': main()
