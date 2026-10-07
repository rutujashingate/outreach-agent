"""Read bounded public-page evidence in isolated, sandboxed Chromium contexts."""
import asyncio
from copy import deepcopy
from pathlib import Path
import re
from urllib.parse import urlsplit, urljoin, unquote
from typing import Protocol

from playwright.async_api import async_playwright
from app.domain.browser import PageEvidence
from app.connectors.browser.network import PublicProxy, parse_public_url
from app.connectors.search import ToolError

EMAIL = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,}")


def extract_emails(text, contact_links):
    found = {}
    for match in EMAIL.finditer(text):
        address = match.group().rstrip('.')
        found[address.lower()] = text[max(0, match.start()-100):match.end()+100]
    for link in contact_links:
        if link.lower().startswith('mailto:'):
            value = unquote(urlsplit(link).path)
            # Accept a single mailbox, never a hidden CC/BCC or several targets.
            if EMAIL.fullmatch(value): found.setdefault(value.lower(), 'Public contact link: ' + value)
    return dict(list(found.items())[:30])


class BrowserTool(Protocol):
    async def read(self, url: str, *, timeout: float = 20, max_chars: int = 15000) -> PageEvidence: ...


class BrowserClient:
    async def available(self):
        async with async_playwright() as driver:
            return Path(driver.chromium.executable_path).exists()

    async def read(self, url, *, timeout=20, max_chars=15000):
        parse_public_url(url)
        try:
            async with asyncio.timeout(timeout), PublicProxy().open() as proxy, async_playwright() as driver:
                browser = await driver.chromium.launch(headless=True, chromium_sandbox=True,
                    proxy={'server': proxy}, args=['--proxy-bypass-list=<-loopback>', '--disable-quic',
                        '--force-webrtc-ip-handling-policy=disable_non_proxied_udp'])
                try:
                    context = await browser.new_context(service_workers='block', accept_downloads=False)
                    async def guard(route):
                        try:
                            parse_public_url(route.request.url)
                            if route.request.method not in {'GET', 'HEAD'} or route.request.resource_type in {'image','media','font'}:
                                raise ToolError('Resource not needed for reading.')
                            await route.continue_()
                        except Exception: await route.abort()
                    await context.route('**/*', guard)
                    await context.route_web_socket('**/*', lambda ws: ws.close())
                    page = await context.new_page()
                    response = await page.goto(url, wait_until='domcontentloaded', timeout=int(timeout * 1000))
                    if response is None or not response.ok: raise ToolError('Page could not be read.')
                    if 'text/html' not in response.headers.get('content-type',''):
                        raise ToolError('Only HTML pages are supported.')
                    # Allow a short, bounded render interval for client-side text.
                    await page.wait_for_timeout(800)
                    parse_public_url(page.url)
                    text = (await page.locator('body').inner_text(timeout=2000))[:max_chars]
                    links = await page.locator('a:visible').evaluate_all('(nodes) => nodes.slice(0, 100).map(a => a.href)')
                    public_links = []
                    for link in links:
                        try: parse_public_url(link)
                        except ToolError: continue
                        if urlsplit(link).hostname == urlsplit(page.url).hostname: public_links.append(link.split('#')[0])
                    return PageEvidence(url=page.url, title=(await page.title())[:500], text=text,
                        links=list(dict.fromkeys(public_links))[:30], emails=extract_emails(text, links))
                finally: await browser.close()
        except (Exception, TimeoutError):
            raise ToolError('Browser could not read this public page within its limits.') from None


class FakeBrowser:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    async def available(self): return True

    async def read(self, url, *, timeout=20, max_chars=15000):
        self.calls.append(url)
        if url not in self.pages: raise ToolError('No example page at this address.')
        return deepcopy(self.pages[url])
