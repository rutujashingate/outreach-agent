"""Owner-authorized Google login and encrypted, renewable Gmail credentials."""
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import secrets
import time

from cryptography.fernet import Fernet, InvalidToken
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import Flow

from app.connectors.search import ToolError
from app.connectors.gmail.client import GmailClient

class RefreshRequest(Request):
    def __call__(self, url, method='GET', body=None, headers=None, timeout=20, **kwargs):
        return super().__call__(url, method=method, body=body, headers=headers, timeout=20, **kwargs)


SCOPES = ['https://www.googleapis.com/auth/gmail.readonly', 'https://www.googleapis.com/auth/gmail.compose']


class CredentialVault:
    def __init__(self, store, key):
        self.store = store
        self.cipher = Fernet(key.encode()) if key else None

    def get(self, name):
        record = self.store.get('secret:' + name)
        if not record: return None
        if self.cipher is None: raise ToolError('Configure OUTREACH_SECRET_KEY to unlock Gmail.')
        try: return json.loads(self.cipher.decrypt(record['sealed'].encode()))
        except (InvalidToken, ValueError): raise ToolError('Gmail credentials could not be unlocked.') from None

    def put(self, name, value):
        if self.cipher is None: raise ToolError('Configure OUTREACH_SECRET_KEY before connecting Gmail.')
        self.store.put('secret:' + name, {'sealed': self.cipher.encrypt(json.dumps(value).encode()).decode()})


class GmailAccount:
    def __init__(self, http, store, settings):
        self.http, self.store, self.settings = http, store, settings
        self.vault = CredentialVault(store, settings.secret_key)
        self.lock = asyncio.Lock()

    def status(self):
        public = self.store.get('gmail_status', {})
        configured = bool(self.settings.google_client_id and self.settings.google_client_secret and self.settings.secret_key)
        return {'connected': False, 'email': None, **public, 'configured': configured,
                'reading_enabled': self.settings.read_gmail, 'sending_enabled': self.settings.sending_enabled}

    def invalidate(self):
        self.store.put('gmail_status', {**self.status(), 'connected': False, 'health': 'reconnect_required'})

    def _flow(self, *, state=None, verifier=None):
        config = {'web': {'client_id': self.settings.google_client_id, 'client_secret': self.settings.google_client_secret,
                         'auth_uri': 'https://accounts.google.com/o/oauth2/auth', 'token_uri': 'https://oauth2.googleapis.com/token'}}
        return Flow.from_client_config(config, scopes=SCOPES, state=state, code_verifier=verifier,
            autogenerate_code_verifier=verifier is None,
            redirect_uri=self.settings.app_url + '/api/connectors/gmail/callback')

    def connect_url(self, session_id):
        if not self.status()['configured']: raise ToolError('Configure Google client ID, client secret and encryption key first.')
        flow = self._flow()
        url, state = flow.authorization_url(access_type='offline', prompt='consent', include_granted_scopes='true')
        self.vault.put('oauth:' + hashlib.sha256(state.encode()).hexdigest(),
                       {'state': state, 'session': session_id, 'verifier': flow.code_verifier, 'expires': time.time() + 600})
        return url

    async def complete(self, state, code, session_id):
        key = 'oauth:' + hashlib.sha256(state.encode()).hexdigest()
        pending = self.vault.get(key)
        self.store.delete('secret:' + key)
        if not pending or pending['expires'] < time.time() or not secrets.compare_digest(pending['session'], session_id):
            raise ToolError('Google sign-in expired or does not match this session. Connect again.')
        async with self.lock:
            try:
                flow = self._flow(state=state, verifier=pending['verifier'])
                await asyncio.to_thread(flow.fetch_token, code=code, timeout=20)
                credentials = flow.credentials
                granted = set(credentials.granted_scopes or credentials.scopes or [])
                if not set(SCOPES) <= granted or not credentials.refresh_token:
                    raise ValueError('Required permissions or offline access missing.')
                response = await self.http.get('https://gmail.googleapis.com/gmail/v1/users/me/profile',
                    headers={'Authorization': 'Bearer ' + credentials.token})
                response.raise_for_status()
                email = response.json()['emailAddress']
                previous = self.status()
                account_id = previous.get("account_id") if (previous.get("email") or "").casefold() == email.casefold() else None
                account_id = account_id or secrets.token_hex(16)
                self.vault.put('gmail', json.loads(credentials.to_json()))
                self.store.put('gmail_status', {'connected': True, 'email': email, 'account_id': account_id,
                    'scopes': sorted(granted), 'health': 'connected', 'connected_at': datetime.now(timezone.utc).isoformat()})
                return self.status()
            except Exception:
                raise ToolError('Google connection failed. Check permissions and try connecting again.') from None

    async def token(self):
        async with self.lock:
            return await self._token()

    async def _token(self):
        # Caller holds the account lock through refresh and any bound action.
        info = self.vault.get('gmail')
        if not info or not self.status().get('connected'): raise ToolError('Connect Gmail before using it.')
        try:
            credentials = Credentials.from_authorized_user_info(info, scopes=SCOPES)
            if not credentials.valid:
                await asyncio.to_thread(credentials.refresh, RefreshRequest())
                self.vault.put('gmail', json.loads(credentials.to_json()))
            return credentials.token
        except Exception:
            self.store.put('gmail_status', {**self.status(), 'connected': False, 'health': 'reconnect_required'})
            raise ToolError('Gmail authorization expired. Reconnect the account.') from None

    async def disconnect(self):
        async with self.lock:
            info = self.vault.get('gmail')
            revoked = True
            try:
                if info:
                    response = await self.http.post('https://oauth2.googleapis.com/revoke',
                        data={'token': info.get('refresh_token') or info.get('token')})
                    revoked = response.is_success
            except Exception: revoked = False
            finally:
                self.store.delete('secret:gmail')
                self.store.put('gmail_status', {'connected': False, 'email': None, 'health': 'disconnected', 'revocation_confirmed': revoked})
            return self.status()


class ConnectedGmail:
    """Refresh before a request; Gmail writes still have no automatic retries."""
    def __init__(self, account):
        self.account = account

    def status(self): return self.account.status()

    def for_run(self, email, account_id): return BoundGmail(self.account, email, account_id)

    async def ensure_account(self, email, account_id):
        status = self.status()
        if not status.get('connected') or status.get('account_id') != account_id or status.get('email', '').casefold() != (email or '').casefold():
            raise ToolError('The connected Gmail account changed. Create a new draft request.')

    async def _client(self):
        return GmailClient(self.account.http, await self.account.token(), self.account.invalidate)

    async def search_threads(self, email, limit=3): return await (await self._client()).search_threads(email, limit)
    async def read_thread(self, thread_id): return await (await self._client()).read_thread(thread_id)
    async def create_draft(self, sender, recipient, draft): return await (await self._client()).create_draft(sender, recipient, draft)
    async def list_drafts(self, query='', limit=5): return await (await self._client()).list_drafts(query, limit)
    async def read_draft(self, draft_id): return await (await self._client()).read_draft(draft_id)
    async def update_draft(self, draft_id, baseline_hash, draft): return await (await self._client()).update_draft(draft_id, baseline_hash, draft)
    async def send(self, sender, recipient, draft):
        raise ToolError('Send manually from Gmail. This connector only creates drafts.')


class BoundGmail(ConnectedGmail):
    """Lock account identity through the network operation, including refresh."""
    def __init__(self, account, email, account_id):
        super().__init__(account)
        self.email, self.account_id = email, account_id

    async def _call(self, method, *args, **kwargs):
        async with self.account.lock:
            await self.ensure_account(self.email, self.account_id)
            client = GmailClient(self.account.http, await self.account._token(), self.account.invalidate)
            return await getattr(client, method)(*args, **kwargs)

    async def search_threads(self, email, limit=3): return await self._call('search_threads', email, limit)
    async def read_thread(self, thread_id): return await self._call('read_thread', thread_id)
    async def create_draft(self, sender, recipient, draft): return await self._call('create_draft', sender, recipient, draft)
    async def list_drafts(self, query='', limit=5): return await self._call('list_drafts', query, limit)
    async def read_draft(self, draft_id): return await self._call('read_draft', draft_id)
    async def update_draft(self, draft_id, baseline_hash, draft): return await self._call('update_draft', draft_id, baseline_hash, draft)
    async def send(self, sender, recipient, draft):
        raise ToolError('Send manually from Gmail. This connector only creates drafts.')
