"""Authentication and request limits shared by the API endpoints."""

from collections import deque
import secrets
import time

from fastapi import HTTPException, Request


async def require_access(request: Request) -> None:
    settings = request.app.state.settings
    if settings.api_key and not secrets.compare_digest(request.headers.get("X-API-Key", ""), settings.api_key):
        raise HTTPException(status_code=401, detail="A valid X-API-Key is required.")
    # The application serves one account. This process-wide limiter bounds
    # that account's requests. Multiple workers need a shared gateway limiter.
    window: deque = request.app.state.request_window
    now = time.monotonic()
    while window and window[0] < now - 60:
        window.popleft()
    if len(window) >= settings.limits.max_requests_per_minute:
        raise HTTPException(status_code=429, detail="Request limit reached; try again later.")
    window.append(now)


def get_manager(request: Request):
    return request.app.state.manager
