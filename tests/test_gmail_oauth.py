"""Check credentials, account binding, refresh and OAuth without Google calls."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import urlsplit, parse_qs

import httpx
import pytest
from cryptography.fernet import Fernet
from google.oauth2.credentials import Credentials
from google.auth.exceptions import RefreshError

from app.connectors.gmail.oauth import GmailAccount, ConnectedGmail, SCOPES
from app.connectors.search import ToolError
from app.settings import Settings
from app.storage.control import ControlStore


def account_for(setup, http):
    settings=Settings(secret_key=Fernet.generate_key().decode(),google_client_id='client-id',google_client_secret='private-client-secret')
    return GmailAccount(http,ControlStore(setup.repository.engine),settings)


def seed(account, token='access-secret', expired=False):
    credentials=Credentials(token,refresh_token='refresh-secret',token_uri='https://oauth2.googleapis.com/token',
                            client_id='client-id',client_secret='private-client-secret',scopes=SCOPES,
                            expiry=datetime.now(timezone.utc).replace(tzinfo=None)+timedelta(hours=-1 if expired else 1))
    import json
    account.vault.put('gmail',json.loads(credentials.to_json()))
    account.store.put('gmail_status',{'connected':True,'email':'user@example.com','account_id':'account-one','health':'connected'})


def test_tokens_are_encrypted_and_absent_from_public_status(make_run_manager):
    setup=make_run_manager()
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={}))) as http:
            account=account_for(setup,http);seed(account)
            raw=account.store.get('secret:gmail')
            assert 'refresh-secret' not in str(raw) and 'access-secret' not in str(raw)
            assert account.vault.get('gmail')['refresh_token']=='refresh-secret'
            assert 'secret' not in str(account.status())
    asyncio.run(check())


def test_refresh_updates_credentials_once_before_request(make_run_manager,monkeypatch):
    setup=make_run_manager(); calls=[]
    def refresh(self, request):
        calls.append('refresh');self.token='renewed-token';self.expiry=datetime.now(timezone.utc).replace(tzinfo=None)+timedelta(hours=1)
    monkeypatch.setattr(Credentials,'refresh',refresh)
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={}))) as http:
            account=account_for(setup,http);seed(account,expired=True)
            assert await account.token()=='renewed-token'
            assert await account.token()=='renewed-token'
            assert account.vault.get('gmail')['token']=='renewed-token'
    asyncio.run(check());assert calls==['refresh']


def test_revoked_refresh_requires_reconnection_without_leaking_provider_text(make_run_manager,monkeypatch):
    setup=make_run_manager()
    def fail(*args): raise RefreshError('private-refresh-secret')
    monkeypatch.setattr(Credentials,'refresh',fail)
    async def check():
        async with httpx.AsyncClient() as http:
            account=account_for(setup,http);seed(account,expired=True)
            with pytest.raises(ToolError,match='Reconnect') as error: await account.token()
            assert 'private-refresh-secret' not in str(error.value)
            assert account.status()['health']=='reconnect_required'
    asyncio.run(check())


def test_oauth_state_is_session_bound_and_single_use(make_run_manager):
    setup=make_run_manager()
    async def check():
        async with httpx.AsyncClient() as http:
            account=account_for(setup,http)
            query=parse_qs(urlsplit(account.connect_url('owner-session')).query)
            assert query['access_type']==['offline'] and 'code_challenge' in query
            with pytest.raises(ToolError,match='session'): await account.complete(query['state'][0],'code','other-session')
            with pytest.raises(ToolError,match='expired'): await account.complete(query['state'][0],'code','owner-session')
    asyncio.run(check())


@pytest.mark.parametrize('scopes', [SCOPES, SCOPES[:1]])
def test_successful_oauth_saves_verified_email_and_missing_scopes_fail(make_run_manager,monkeypatch,scopes):
    setup=make_run_manager()
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'emailAddress':'user@example.com'}))) as http:
            account=account_for(setup,http)
            state=parse_qs(urlsplit(account.connect_url('session')).query)['state'][0]
            credentials=Credentials('token',refresh_token='refresh',token_uri='https://oauth2.googleapis.com/token',client_id='id',client_secret='secret',scopes=scopes)
            monkeypatch.setattr(account,'_flow',lambda **kwargs:SimpleNamespace(fetch_token=lambda **kw:None,credentials=credentials))
            if scopes != SCOPES:
                with pytest.raises(ToolError, match='permissions'): await account.complete(state,'code','session')
                assert account.vault.get('gmail') is None
                return
            result=await account.complete(state,'code','session')
            assert result['email']=='user@example.com' and result['connected']
    asyncio.run(check())


def test_reconnecting_same_address_retains_account_binding(make_run_manager,monkeypatch):
    setup=make_run_manager()
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'emailAddress':'user@example.com'}))) as http:
            account=account_for(setup,http);seed(account)
            state=parse_qs(urlsplit(account.connect_url('session')).query)['state'][0]
            credentials=Credentials('token',refresh_token='refresh',token_uri='https://oauth2.googleapis.com/token',client_id='id',client_secret='secret',scopes=SCOPES)
            monkeypatch.setattr(account,'_flow',lambda **kwargs:SimpleNamespace(fetch_token=lambda **kw:None,credentials=credentials))
            assert (await account.complete(state,'code','session'))['account_id']=='account-one'
    asyncio.run(check())


def test_account_change_prevents_gmail_write(make_run_manager,records):
    from app.domain.schemas import EmailDraft
    from app.domain.workflow import Sender,Recipient
    setup=make_run_manager(); requests=[]
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:requests.append(r) or httpx.Response(200,json={'id':'message'}))) as http:
            account=account_for(setup,http);seed(account)
            bound=ConnectedGmail(account).for_run('user@example.com','old-account')
            with pytest.raises(ToolError,match='account changed'):
                await bound.send(Sender(email='user@example.com'),Recipient(email='contact@example.com'),records[EmailDraft])
    asyncio.run(check());assert requests==[]


def test_disconnect_clears_tokens_even_if_revocation_is_unavailable(make_run_manager):
    setup=make_run_manager()
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(503))) as http:
            account=account_for(setup,http);seed(account)
            status=await account.disconnect()
            assert not status['connected'] and not status['revocation_confirmed']
            assert account.vault.get('gmail') is None
    asyncio.run(check())
