"""One owner, opaque sessions, and CSRF protection for browser actions."""
import hashlib
import secrets
import time

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import HTTPException, Request


class OwnerAuth:
    def __init__(self, store, password):
        self.store, self.password_hash = store, PasswordHasher().hash(password) if password else None

    def login(self, password, address):
        # Persist the login throttle so restarting does not reset it.
        key = 'login:' + hashlib.sha256(address.encode()).hexdigest()
        attempts = self.store.get(key, {'count': 0, 'until': 0})
        if attempts['until'] < time.time(): attempts = {'count': 0, 'until': time.time() + 60}
        if attempts['count'] >= 5: raise HTTPException(429, 'Too many attempts; wait one minute.')
        attempts['count'] += 1; self.store.put(key, attempts)
        try:
            if not self.password_hash or not PasswordHasher().verify(self.password_hash, password): raise ValueError()
        except (VerificationError, InvalidHashError, ValueError): raise HTTPException(401, 'Invalid owner password.') from None
        self.store.delete(key)
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        session_id = hashlib.sha256(token.encode()).hexdigest()
        self.store.put('session:' + session_id, {'csrf': csrf, 'expires': time.time() + 12 * 3600,
            'password_version': hashlib.sha256(self.password_hash.encode()).hexdigest()})
        return token, csrf

    def session(self, request):
        token = request.cookies.get('outreach_session', '')
        session_id = hashlib.sha256(token.encode()).hexdigest()
        saved = self.store.get('session:' + session_id)
        if not saved or saved['expires'] < time.time(): raise HTTPException(401, 'Sign in to continue.')
        # A process restart expires sessions; sign in again. Saved workflow
        # approvals remain available independently from browser sessions.
        if saved.get('password_version') != hashlib.sha256((self.password_hash or '').encode()).hexdigest():
            raise HTTPException(401, 'Sign in again after the service restart.')
        return session_id, saved


async def require_owner(request: Request):
    settings, auth = request.app.state.settings, request.app.state.auth
    supplied = request.headers.get('X-API-Key', '')
    if settings.api_key and secrets.compare_digest(supplied, settings.api_key): return 'api-owner'
    session_id, saved = auth.session(request)
    if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
        origin = request.headers.get('origin')
        if origin and origin.rstrip('/') != settings.app_url: raise HTTPException(403, 'Invalid request origin.')
        if not secrets.compare_digest(request.headers.get('X-CSRF-Token', ''), saved['csrf']):
            raise HTTPException(403, 'Invalid request token; sign in again.')
    return session_id
