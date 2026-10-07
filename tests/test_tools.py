"""Verify real HTTP adapters using local transports that return every response."""

import asyncio
import base64
from email import message_from_bytes
import json

import httpx
import pytest

from app.domain.schemas import EmailDraft
from app.domain.workflow import Recipient, SearchResult, Sender
from app.connectors.gmail.client import GmailClient, contact_messages, encode_message
from app.connectors.search import BraveSearchTool, FakeSearchTool, ToolError


def test_search_uses_goal_query_and_preserves_url():
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"web": {"results": [{"title": "Example AI", "url": "https://example.com/ai", "description": "AI APIs"}]}})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            return await BraveSearchTool(http, "test-key").search("AI API startups")
    results = asyncio.run(run())
    assert results == [SearchResult(title="Example AI", url="https://example.com/ai", description="AI APIs")]
    assert requests[0].url.params["q"] == "AI API startups"
    assert requests[0].headers["X-Subscription-Token"] == "test-key"


@pytest.mark.parametrize("status,payload", [(401, {}), (429, {}), (500, {}), (200, {"web": {"results": [{}]}})])
def test_search_failures_are_explicit_and_do_not_expose_key(status, payload):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(status, json=payload))) as http:
            with pytest.raises(ToolError) as caught:
                await BraveSearchTool(http, "private-test-key").search("AI startups")
            assert "private-test-key" not in str(caught.value)
    asyncio.run(run())


def test_empty_search_and_fake_results_are_separate():
    fake = FakeSearchTool([SearchResult(title="Example", url="https://example.com", description="Evidence")])
    first = asyncio.run(fake.search("first"))
    first.clear()
    assert len(asyncio.run(fake.search("second"))) == 1
    assert fake.queries == ["first", "second"]


def test_gmail_reads_and_writes_expected_rest_requests():
    requests = []
    def respond(request):
        requests.append(request)
        path = request.url.path
        if path.endswith("/threads"):
            return httpx.Response(200, json={"threads": [{"id": "t1"}]})
        if path.endswith("/threads/t1"):
            return httpx.Response(200, json={"id": "t1", "messages": []})
        if path.endswith("/drafts"):
            return httpx.Response(200, json={"id": "d1", "message": {"id": "m1", "threadId": "t1"}})
        return httpx.Response(200, json={"id": "m2", "threadId": "t1"})
    sender, recipient = Sender(name="User", email="user@example.com"), Recipient(email="contact@example.com")
    draft = EmailDraft(prospect_id="p1", subject="A conversation", body="Would a conversation help?")
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            tool = GmailClient(http, "test-token")
            assert await tool.search_threads(recipient.email) == ["t1"]
            assert (await tool.read_thread("t1"))["id"] == "t1"
            assert (await tool.create_draft(sender, recipient, draft))["id"] == "d1"
            assert (await tool.send(sender, recipient, draft))["id"] == "m2"
    asyncio.run(run())
    assert [request.method for request in requests] == ["GET", "GET", "POST", "POST"]
    assert requests[0].url.params["q"] == "{from:contact@example.com to:contact@example.com}"
    assert requests[1].url.params["format"] == "full"
    assert all(request.headers["Authorization"] == "Bearer test-token" for request in requests)
    data = json.loads(requests[2].content)
    mime = message_from_bytes(base64.urlsafe_b64decode(data["message"]["raw"]))
    assert mime["To"] == recipient.email
    assert mime["Subject"] == draft.subject
    assert "Would a conversation help?" in mime.get_payload()


@pytest.mark.parametrize("operation", ["draft", "send"])
def test_gmail_post_timeout_is_attempted_once(operation):
    calls = []
    def respond(request):
        calls.append(request)
        raise httpx.ReadTimeout("The response was lost.")
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            tool = GmailClient(http, "test-token")
            method = tool.create_draft if operation == "draft" else tool.send
            with pytest.raises(ToolError):
                await method(Sender(email="user@example.com"), Recipient(email="contact@example.com"),
                             EmailDraft(prospect_id="p1", subject="Hello", body="A question."))
    asyncio.run(run())
    assert len(calls) == 1


def test_mime_headers_cannot_inject_another_recipient():
    with pytest.raises(ValueError, match="headers"):
        encode_message(Sender(email="user@example.com"), Recipient(email="contact@example.com"),
                       EmailDraft(prospect_id="p1", subject="Hello\nBcc: other@example.com", body="Hello"))


def test_gmail_message_parsing_keeps_correct_contact_and_plain_text():
    data = base64.urlsafe_b64encode(b"Please unsubscribe me.").decode().rstrip("=")
    def message(identifier, sender):
        return {"id": identifier, "internalDate": "1700000000000", "payload": {
            "mimeType": "multipart/alternative", "headers": [{"name": "From", "value": sender}, {"name": "To", "value": "user@example.com"}],
            "parts": [{"mimeType": "text/plain", "body": {"data": data}}, {"mimeType": "text/html", "body": {"data": data}}],
        }}
    parsed = contact_messages({"messages": [message("m1", "Contact <contact@example.com>"), message("m2", "other@example.com")]}, "contact@example.com")
    assert len(parsed) == 1
    assert parsed[0]["body"] == "Please unsubscribe me."
    assert parsed[0]["source"] == "gmail:m1"
    assert parsed[0]["inbound"] is True
    assert parsed[0]["sent_at"].tzinfo is not None
