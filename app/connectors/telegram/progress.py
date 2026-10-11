"""Best-effort typing and one edited status message for each queued task.

This never carries approval controls or replaces the durable final-message
outbox. A failed status update cannot fail or repeat an outreach action.
"""
import asyncio
import time

from app.connectors.search import ToolError
from app.connectors.telegram.client import RateLimited


class TelegramProgress:
    def __init__(self, tracker, client, owner, *, clock=time.monotonic):
        self.tracker, self.client, self.owner, self.clock = tracker, client, owner, clock
        self.sent, self.retry_at, self.next_typing, self.next_message = {}, 0, 0, 0

    async def _call(self, method, **payload):
        async with asyncio.timeout(5):
            return await self.client.call(method, chat_id=self.owner, **payload)

    async def tick(self):
        """Send at most one status edit per tick, plus a four-second typing pulse."""
        moment = self.clock()
        items = self.tracker.snapshot()
        if not self.owner or moment < self.retry_at:
            return
        for item in items:
            key, previous = item['id'], self.sent.get(item['id'])
            if item['finished'] is not None and previous is None:
                self.tracker.discard(key)  # Fast tasks need only their final reply.
                continue
            if previous and previous.get('blocked'):
                if item['finished'] is not None:
                    self.tracker.discard(key); self.sent.pop(key, None)
                continue
            start = item['started'] if item['started'] is not None else item['created']
            elapsed = int((item['finished'] if item['finished'] is not None else moment) - start)
            signature = (item['revision'], elapsed // 15, item['finished'] is not None)
            if moment < self.next_message or previous and (moment < previous['next_edit'] or signature == previous['signature']):
                continue
            text = f"{item['label']}\nElapsed: {elapsed}s"
            if item['run_id']: text += '\nTask: ' + item['run_id']
            try:
                if previous:
                    await self._call('editMessageText', message_id=previous['message_id'], text=text)
                    message_id = previous['message_id']
                else:
                    response = await self._call('sendMessage', text=text)
                    message_id = response['message_id']
                self.sent[key] = {'message_id': message_id, 'signature': signature, 'next_edit': moment + 3}
                self.next_message = moment + 1
                if item['finished'] is not None:
                    self.tracker.discard(key); self.sent.pop(key, None)
            except RateLimited as error:
                self.retry_at = moment + error.delay
                return
            except (ToolError, TimeoutError, KeyError, TypeError):
                # A lost send response may mean the status already arrived.
                # Suppress repetition rather than creating duplicate messages.
                self.sent[key] = {'blocked': True}
            break
        if any(item['started'] is not None and item['finished'] is None for item in items) and moment >= self.next_typing:
            try:
                await self._call('sendChatAction', action='typing')
                self.next_typing = moment + 4
            except RateLimited as error:
                self.retry_at = moment + error.delay
            except (ToolError, TimeoutError):
                self.next_typing = moment + 10
