"""Run a complete local demonstration with fictional data and fake tools.

Run `python -m app.demo` for a command-line example, or
`uvicorn app.demo:app --port 8001` for the same simulation through the API.
This demonstrates control flow, not actual research or model quality.
"""

import asyncio
from contextlib import asynccontextmanager
import json

from langgraph.checkpoint.memory import InMemorySaver

from app.db.database import create_database
from app.main import create_app
from app.memory.repository import Repository
from app.models.client import FakeModelClient
from app.models.schemas import Prospect
from app.models.workflow import ApprovalSubmission, SearchResult, Sender, WorkflowRequest
from app.orchestration.runs import RunManager
from app.settings import Settings
from app.tools.gmail import FakeGmailClient
from app.tools.search import FakeSearchTool

DEMO_PROSPECT = Prospect(id="p1", company_name="Example University", decision_maker_name="Ada Example",
    decision_maker_role="Professor", signals=["Studies AI observability"], sources=["https://example.com/lab"])


class DemoModelClient(FakeModelClient):
    """Feed the existing fake client fictional responses by requested record type."""

    def __init__(self):
        super().__init__([])

    async def generate_structured(self, *, instructions, input_text, response_model):
        task = response_model.__name__
        if task == "OutreachGoal":
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


def build_demo_manager(*, repository=None, checkpointer=None, settings=None):
    @asynccontextmanager
    async def client_factory():
        yield DemoModelClient()
    return RunManager(repository or Repository(create_database()), checkpointer or InMemorySaver(),
        settings=settings or Settings(checkpoint_backend="memory"), client_factory=client_factory,
        search=FakeSearchTool([SearchResult(title="Example University: Ada Example", url="https://example.com/lab",
            description="Ada Example studies AI observability at Example University.")]), gmail=FakeGmailClient())


async def demonstrate():
    manager = build_demo_manager()
    try:
        response = await manager.start(demo_request())
        print(f"Simulated run {response.state.run_id}: {response.state.current_step}")
        request = response.state.approval_requests[0]
        response = await manager.resume(response.state.run_id, ApprovalSubmission(decisions=[{
            "prospect_id": request.prospect.id, "version": request.version,
            "fingerprint": request.fingerprint, "action": "approve",
        }]))
        print(f"After simulated approval: {response.state.outcomes['p1'].status}")
        print("Fake Gmail calls:", [name for name, data in manager.gmail.calls])
        print("No external services were called and no real draft or email was created.")
    finally:
        manager.repository.engine.dispose()


# This separate application is deliberately a simulation and has no real SDKs.
app = create_app(manager=build_demo_manager())

if __name__ == "__main__":
    asyncio.run(demonstrate())
