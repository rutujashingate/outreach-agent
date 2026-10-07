"""Optional Chromium checks against a locally served fictional public website.

RUN_BROWSER_TESTS=1 python -m pytest tests/test_browser_integration.py
The test-only network adapter maps public.test to a local fixture server. Real
production URL validation is still used; no external website is contacted.
"""
import asyncio
import os
import pytest
from app.connectors.browser.client import BrowserClient
from app.connectors.browser import network
from app.connectors.search import ToolError

pytestmark=pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS')!='1',reason='Opt into installed Chromium integration checks')


def test_chromium_renders_javascript_but_blocks_writes_and_private_redirects(monkeypatch):
    requests=[]
    async def exercise():
        async def handle(reader,writer):
            try:
                data=await reader.readuntil(b'\r\n\r\n');line=data.split(b'\r\n')[0].decode();requests.append(line)
                if '/redirect ' in line:
                    reply=b'HTTP/1.1 302 Found\r\nLocation: http://127.0.0.1/private\r\nContent-Length: 0\r\nConnection: close\r\n\r\n'
                else:
                    body=b'''<html><head><title>Fixture research</title></head><body><div id="root"></div><a href="mailto:contact@example.com">Email</a><script>document.getElementById('root').textContent='Example Company: AI observability';fetch('/write',{method:'POST',body:'blocked'}).catch(()=>{});fetch('http://127.0.0.1/private').catch(()=>{});</script></body></html>'''
                    reply=b'HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\nContent-Length: '+str(len(body)).encode()+b'\r\n\r\n'+body
                writer.write(reply);await writer.drain()
            finally:writer.close()
        server=await asyncio.start_server(handle,'127.0.0.1',0)
        port=server.sockets[0].getsockname()[1]
        original=asyncio.open_connection
        async def resolve(host,port):
            assert host=='public.test';return '93.184.215.14'
        async def connect(host,port,**kwargs):
            assert host=='93.184.215.14';return await original('127.0.0.1',server.sockets[0].getsockname()[1],**kwargs)
        monkeypatch.setattr(network,'public_address',resolve)
        monkeypatch.setattr(network.asyncio,'open_connection',connect)
        try:
            page=await BrowserClient().read('http://public.test/')
            assert 'Example Company: AI observability' in page.text
            assert 'contact@example.com' in page.emails
            with pytest.raises(ToolError):await BrowserClient().read('http://public.test/redirect')
        finally:server.close();await server.wait_closed()
    asyncio.run(exercise())
    assert not any('POST' in line or '/private' in line for line in requests)
