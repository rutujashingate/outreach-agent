"""Small Telegram HTTP adapter plus a network-free test substitute."""
import httpx
from pathlib import PurePosixPath
from urllib.parse import quote
from app.connectors.search import ToolError


class RateLimited(ToolError):
    def __init__(self, delay): self.delay = max(1, min(int(delay), 3600))


class TelegramClient:
    def __init__(self, http, token): self.http, self.token = http, token

    async def call(self, method, **payload):
        try:
            response = await self.http.post(f'https://api.telegram.org/bot{self.token}/{method}', json=payload,
                                           timeout=40 if method == 'getUpdates' else 20)
            data = response.json()
            if not isinstance(data, dict): raise ToolError('Invalid Telegram response.')
            if response.status_code == 429 or data.get('error_code') == 429:
                raise RateLimited(data.get('parameters', {}).get('retry_after', 5))
            if not response.is_success or not data.get('ok'): raise ToolError('Telegram request failed.')
            return data['result']
        except (httpx.HTTPError, ValueError, KeyError): raise ToolError('Telegram connection failed.') from None


    async def download_file(self, file_id, maximum):
        metadata = await self.call('getFile', file_id=file_id)
        path = metadata.get('file_path', '')
        if not path or path.startswith('/') or '..' in PurePosixPath(path).parts or ':' in path:
            raise ToolError('Telegram did not return a usable file path.')
        if metadata.get('file_size', 0) > maximum: raise ToolError('Files may be at most 10 MiB.')
        data = bytearray()
        try:
            async with self.http.stream('GET', f'https://api.telegram.org/file/bot{self.token}/' + quote(path, safe='/'),
                                        timeout=30, follow_redirects=False) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    if len(data) + len(chunk) > maximum: raise ToolError('Files may be at most 10 MiB.')
                    data.extend(chunk)
        except httpx.HTTPError:
            raise ToolError('Telegram file download failed. Please upload the file again.') from None
        return bytes(data)


class FakeTelegram:
    def __init__(self): self.calls, self.updates, self.files = [], [], {}
    async def call(self, method, **payload):
        self.calls.append((method, payload))
        if method == 'getUpdates':
            pending = [u for u in self.updates if u['update_id'] >= payload.get('offset', 0)]
            self.updates = []
            return pending
        if method == 'getWebhookInfo': return {'url': ''}
        if method == 'getMe': return {'username': 'outreach_demo_bot'}
        return {'message_id': len(self.calls)}

    async def download_file(self, file_id, maximum):
        self.calls.append(('download', {'file_id': file_id}))
        data = self.files[file_id]
        if len(data) > maximum: raise ToolError('Files may be at most 10 MiB.')
        return data
