"""Read Gmail and create approved messages through the official REST API.

No method runs at import time. The workflow, approval, and action ledger decide
whether a write method may be called. POST requests are never automatically
retried because a lost response may hide an already completed external action.
"""

import base64
from copy import deepcopy
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr, getaddresses
from typing import Protocol
from urllib.parse import quote

import httpx

from app.domain.schemas import EmailDraft
from app.domain.workflow import Recipient, Sender
from app.connectors.search import ToolError


class GmailTool(Protocol):
    async def search_threads(self, email: str, limit: int = 3) -> list[str]: ...
    async def read_thread(self, thread_id: str) -> dict: ...
    async def create_draft(self, sender: Sender, recipient: Recipient, draft: EmailDraft) -> dict: ...
    async def send(self, sender: Sender, recipient: Recipient, draft: EmailDraft) -> dict: ...


def encode_message(sender: Sender, recipient: Recipient, draft: EmailDraft) -> str:
    if sender.email is None:
        raise ValueError("Gmail actions require a sender email.")
    for value in (sender.name, sender.email, recipient.email, draft.subject):
        if "\r" in value or "\n" in value:
            raise ValueError("Email headers must not contain line breaks.")
    message = EmailMessage()
    message["From"] = formataddr((sender.name, sender.email))
    message["To"], message["Subject"] = recipient.email, draft.subject
    message.set_content(draft.body)
    return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")


def _plain_text(payload: dict) -> str:
    pieces: list[str] = []
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        data = payload["body"]["data"]
        pieces.append(base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace"))
    for part in payload.get("parts", []):
        pieces.append(_plain_text(part))
    return "\n".join(piece for piece in pieces if piece)


def contact_messages(thread: dict, email: str) -> list[dict]:
    """Return plain-text messages involving this exact address, not a namesake."""
    messages = []
    for message in thread.get("messages", []):
        payload = message.get("payload", {})
        headers = {item["name"].casefold(): item["value"] for item in payload.get("headers", [])}
        parties = {address.casefold() for _, address in getaddresses([
            headers.get("from", ""), headers.get("to", ""), headers.get("cc", ""),
        ])}
        if email.casefold() not in parties:
            continue
        text = _plain_text(payload)
        if not text.strip():
            continue
        sent_at = (datetime.fromtimestamp(int(message["internalDate"]) / 1000, timezone.utc)
                   if message.get("internalDate") is not None else None)
        messages.append({"source": f"gmail:{message['id']}", "body": text, "sent_at": sent_at,
                         "from_addresses": [address.casefold() for _, address in getaddresses([headers.get("from", "")])],
                         "inbound": email.casefold() in {address.casefold() for _, address in
                         getaddresses([headers.get("from", "")])}})
    return messages


class GmailClient:
    def __init__(self, client: httpx.AsyncClient, access_token: str):
        if not access_token.strip():
            raise ValueError("GMAIL_ACCESS_TOKEN is required for Gmail access.")
        self.client, self.access_token = client, access_token

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            response = await self.client.request(
                method, "https://gmail.googleapis.com/gmail/v1/users/me/" + path,
                headers={"Authorization": f"Bearer {self.access_token}"}, **kwargs,
            )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("Expected an object.")
            return data
        except (httpx.HTTPError, ValueError) as error:
            raise ToolError("Gmail request failed; check credentials and action history.") from error

    async def search_threads(self, email: str, limit: int = 3) -> list[str]:
        data = await self._request("GET", "threads", params={
            "q": f"{{from:{email} to:{email}}}", "maxResults": min(max(limit, 1), 100),
        })
        return [thread["id"] for thread in data.get("threads", [])]

    async def read_thread(self, thread_id: str) -> dict:
        return await self._request("GET", "threads/" + quote(thread_id, safe=""), params={"format": "full"})

    async def create_draft(self, sender: Sender, recipient: Recipient, draft: EmailDraft) -> dict:
        result = await self._request("POST", "drafts", json={
            "message": {"raw": encode_message(sender, recipient, draft)},
        })
        if not isinstance(result.get("id"), str) or not result["id"]:
            raise ToolError("Gmail draft response had no identifier.")
        return result

    async def send(self, sender: Sender, recipient: Recipient, draft: EmailDraft) -> dict:
        result = await self._request("POST", "messages/send", json={
            "raw": encode_message(sender, recipient, draft),
        })
        if not isinstance(result.get("id"), str) or not result["id"]:
            raise ToolError("Gmail send response had no identifier.")
        return result


class FakeGmailClient:
    """Record simulated Gmail operations. No email or draft leaves the computer."""

    def __init__(self, threads: dict[str, dict] | None = None):
        self.threads = deepcopy(threads or {})
        self.calls: list[tuple[str, object]] = []

    async def search_threads(self, email: str, limit: int = 3) -> list[str]:
        self.calls.append(("search", email))
        return [key for key, thread in self.threads.items() if contact_messages(thread, email)][:limit]

    async def read_thread(self, thread_id: str) -> dict:
        self.calls.append(("read", thread_id))
        return deepcopy(self.threads[thread_id])

    async def create_draft(self, sender: Sender, recipient: Recipient, draft: EmailDraft) -> dict:
        self.calls.append(("draft", {"to": recipient.email, **draft.model_dump()}))
        return {"id": f"draft-{len(self.calls)}", "message": {"id": "message-1", "threadId": "thread-1"}}

    async def send(self, sender: Sender, recipient: Recipient, draft: EmailDraft) -> dict:
        self.calls.append(("send", {"to": recipient.email, **draft.model_dump()}))
        return {"id": f"message-{len(self.calls)}", "threadId": "thread-1"}
