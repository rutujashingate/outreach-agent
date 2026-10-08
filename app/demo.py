"""Run a complete local demonstration with fictional data and fake tools.

Start with `python -m app.main --demo` and open the dashboard.
This demonstrates control flow, not actual research or model quality.
"""

from contextlib import asynccontextmanager
import json

from langgraph.checkpoint.memory import InMemorySaver

from app.storage.database import create_database
from app.storage.repository import Repository
from app.llm.client import FakeModelClient
from app.domain.schemas import Prospect
from app.domain.workflow import SearchResult, Sender, WorkflowRequest
from app.services.runs import RunManager
from app.settings import Settings
from app.connectors.gmail.client import FakeGmailClient
from app.connectors.search import FakeSearchTool

DEMO_PROSPECT = Prospect(id="p1", company_name="Example University", decision_maker_name="Ada Example",
    decision_maker_role="Professor", signals=["Studies AI observability"], sources=["https://example.com/lab"])


class DemoModelClient(FakeModelClient):
    """Feed the existing fake client fictional responses by requested record type."""

    def __init__(self):
        super().__init__([])

    async def generate_structured(self, *, instructions, input_text, response_model):
        task = response_model.__name__
        if task == "OutreachGoal":
            if input_text.startswith('{'):
                input_text = json.loads(input_text)['goal']
            result = {"raw_goal": input_text, "goal_type": "academic", "objective": "Find a PhD supervisor",
                "target_entity": "professor", "target_description": "Professors studying AI observability",
                "desired_outcome": "Discuss PhD supervision", "constraints": [], "research_signals": ["AI observability"]}
        elif task == "ResearchResult":
            material = json.loads(input_text)["research_material"]
            result = {"prospects": [DEMO_PROSPECT.model_dump()] if DEMO_PROSPECT.company_name in material else []}
        elif task == "Qualification":
            result = {"prospect_id": "p1", "score": 86, "qualified": True, "reasons": ["Research topic matches the example goal."]}
        elif task == "OutreachStrategy":
            result = {"prospect_id": "p1", "trigger": "Shared research topic", "pain_hypothesis": "Unknown",
                "value_proposition": "Discuss possible research collaboration", "personalization_hook": "AI observability research",
                "call_to_action": "Ask about PhD supervision"}
        elif task == "EmailDraft":
            result = {"prospect_id": "p1", "subject": "PhD research in AI observability",
                "body": "Dear Professor Example,\n\nI am interested in your AI observability research. Would you be open to discussing PhD supervision?\n"}
        elif task == "ReviewResult":
            result = {"prospect_id": "p1", "approved": True, "score": 0.9, "issues": []}
        elif task == "ReplyClassification":
            body = json.loads(input_text)["body"]
            result = {"category": "question" if "?" in body else "positive", "evidence_quote": body}
        elif task == "MemoryExtraction":
            body = json.loads(input_text)["message"]
            result = {"facts": [{"kind": "relationship", "value": body, "evidence_quote": body}]}
        else:
            raise ValueError("The demonstration does not support this record type.")
        self._responses.append(result)
        return await super().generate_structured(instructions=instructions, input_text=input_text, response_model=response_model)


def demo_request() -> WorkflowRequest:
    return WorkflowRequest(goal="Find professors studying AI observability for PhD outreach.",
        research_material=DEMO_PROSPECT.model_dump_json(),
        sender=Sender(name="Example Student", email="student@example.com"),
        recipients={"p1": {"email": "professor@example.com"}}, gmail_action="draft")


class DemoGmail(FakeGmailClient):
    def status(self):
        return {"connected": True, "configured": True, "email": "student@example.com", "account_id": "demo-account", "health": "simulated"}


def build_demo_manager(*, repository=None, checkpointer=None, settings=None):
    @asynccontextmanager
    async def client_factory():
        yield DemoModelClient()
    from app.connectors.browser.client import FakeBrowser
    from app.domain.browser import PageEvidence
    browser = FakeBrowser({"https://example.com/lab": PageEvidence(url="https://example.com/lab", title="Example University",
        text="Example University. Ada Example studies AI observability. Contact professor@example.com.",
        emails={"professor@example.com": "Ada Example — contact professor@example.com"})})
    return RunManager(repository or Repository(create_database()), checkpointer or InMemorySaver(),
        settings=settings or Settings(checkpoint_backend="memory"), client_factory=client_factory,
        search=FakeSearchTool([SearchResult(title="Example University: Ada Example", url="https://example.com/lab",
            description="Ada Example studies AI observability at Example University.")]),
        gmail=DemoGmail({'thread-1': {'messages': []}}), browser=browser)
