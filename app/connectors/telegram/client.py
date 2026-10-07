"""Small Telegram HTTP adapter plus a network-free test substitute."""
import httpx
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


class FakeTelegram:
    def __init__(self): self.calls, self.updates = [], []
    async def call(self, method, **payload):
        self.calls.append((method, payload))
        if method == 'getUpdates':
            pending = [u for u in self.updates if u['update_id'] >= payload.get('offset', 0)]
            self.updates = []
            return pending
        if method == 'getWebhookInfo': return {'url': ''}
        if method == 'getMe': return {'username': 'outreach_demo_bot'}
        return {'message_id': len(self.calls)}
