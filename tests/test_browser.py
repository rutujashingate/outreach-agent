"""Public page boundaries and sourced recipient selection without live websites."""
import asyncio
from unittest.mock import AsyncMock
import pytest
from app.connectors.browser.network import parse_public_url, public_address
from app.connectors.browser.client import extract_emails, FakeBrowser
from app.connectors.browser.managed import ManagedBrowser
from app.connectors.search import ToolError
from app.domain.browser import PageEvidence
from app.services.application import AgentService
from app.services.limits import Limits, LimitExceeded
from app.settings import Settings


@pytest.mark.parametrize('url', ['file:///etc/passwd', 'http://localhost', 'http://127.0.0.1', 'http://169.254.169.254',
    'http://[::1]', 'http://192.168.1.1', 'http://10.0.0.1', 'https://user:pass@example.com', 'ftp://example.com', 'https://example.com:8000'])
def test_browser_rejects_unsafe_destinations(url):
    with pytest.raises(ToolError): parse_public_url(url)


def test_dns_checks_all_addresses_and_returns_the_pinned_public_ip(monkeypatch):
    async def check():
        loop = asyncio.get_running_loop()
        monkeypatch.setattr(loop, 'getaddrinfo', AsyncMock(return_value=[(2,1,6,'',('93.184.215.14',443)), (2,1,6,'',('127.0.0.1',443))]))
        with pytest.raises(ToolError): await public_address('example.com', 443)
        loop.getaddrinfo.return_value = [(2,1,6,'',('93.184.215.14',443))]
        assert await public_address('example.com', 443) == '93.184.215.14'
    asyncio.run(check())


def test_addresses_must_appear_in_text_or_single_recipient_links():
    found = extract_emails('Contact Ada at ada@example.com.', ['mailto:team@example.com', 'mailto:a@example.com,b@example.com'])
    assert set(found) == {'ada@example.com', 'team@example.com'}
    assert 'Ada' in found['ada@example.com']


def test_page_budget_is_saved_and_successful_evidence_is_reused(make_run_manager, workflow_data):
    setup = make_run_manager(); service = AgentService(setup.manager)
    job = service.start(workflow_data.request, 'start')
    tool = FakeBrowser({'https://example.com': PageEvidence(url='https://example.com', text='Evidence')})
    async def check():
        reader = ManagedBrowser(tool, setup.repository, job['run_id'], Limits(max_browser_pages=1))
        assert (await reader.read('https://example.com')).text == 'Evidence'
        fresh = ManagedBrowser(tool, setup.repository, job['run_id'], Limits(max_browser_pages=1))
        assert (await fresh.read('https://example.com')).text == 'Evidence'
        with pytest.raises(LimitExceeded): await fresh.read('https://other.example.com')
    asyncio.run(check())
    assert len(tool.calls) == 1


@pytest.mark.parametrize('emails,expected', [({'one@example.com':'Contact one@example.com'}, 'awaiting_approval'),
    ({'one@example.com':'Contact one@example.com','two@example.com':'Contact two@example.com'}, 'awaiting_recipients'),
    ({}, 'awaiting_recipients')])
def test_public_email_candidates_are_resolved_before_contact_rules(make_run_manager, workflow_data, emails, expected):
    setup = make_run_manager(); service = AgentService(setup.manager)
    prospect = workflow_data.responses[1]['prospects'][0]
    url = prospect['sources'][0]
    setup.manager.browser = FakeBrowser({url: PageEvidence(url=url, text=str(prospect), emails=emails)})
    request = workflow_data.request.model_copy(update={'use_browser':True,'discover_emails':True,'seed_urls':[url], 'recipients':{}})
    job = service.start(request, 'start'); asyncio.run(service.execute_one())
    state = service.state(job['run_id'])
    assert state.state.current_step == expected
    if expected == 'awaiting_recipients':
        assert len(setup.client.calls) == 3
        service.select_recipients(job['run_id'], {'p1':{'email':'owner-supplied@example.com'}}, 'select')
        asyncio.run(service.execute_one())
        assert service.state(job['run_id']).awaiting_approval
        assert len(setup.client.calls) == 6


def test_explicit_recipient_takes_precedence(make_run_manager, workflow_data):
    setup = make_run_manager(); service = AgentService(setup.manager)
    prospect = workflow_data.responses[1]['prospects'][0]; url=prospect['sources'][0]
    setup.manager.browser = FakeBrowser({url: PageEvidence(url=url,text=str(prospect),emails={'another@example.com':'Contact another@example.com'})})
    job=service.start(workflow_data.request.model_copy(update={'use_browser':True,'discover_emails':True,'seed_urls':[url]}),'start')
    asyncio.run(service.execute_one())
    assert service.state(job['run_id']).state.recipients['p1'].email == 'contact@example.com'
