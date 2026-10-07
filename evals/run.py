"""Run local workflow evaluations, or explicitly opt into live model measurement.

python -m evals.run                  # Fake clients; no network or model charges.
python -m evals.run --live           # Real configured model; no Gmail actions.
python -m evals.run --output .data/evaluations.json
"""

import argparse
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import time

from langgraph.checkpoint.memory import InMemorySaver

from app.storage.database import create_database
from app.storage.repository import Repository
from app.llm.client import FakeModelClient
from app.domain.workflow import WorkflowRequest
from app.services.runs import RunManager
from app.settings import Settings
from evals.scoring import score_run


def case_request(case: dict) -> WorkflowRequest:
    name, source, hook = case["target_names"][0], case["sources"][0], case["hook"]
    material = f"{name} is working on {hook}. Source: {source}"
    return WorkflowRequest(goal=case["goal"], research_material=material,
                           recipients={name: {"email": "contact@example.com"}})


def scripted_client(case: dict) -> FakeModelClient:
    return FakeModelClient([
        {"raw_goal": case["goal"], "goal_type": case["goal_type"], "objective": case["goal"],
         "target_entity": "organization", "target_description": case["target_names"][0], "desired_outcome": "Discuss the opportunity"},
        {"prospects": [{"id": "p1", "company_name": case["target_names"][0], "signals": [case["hook"]], "sources": case["sources"]}]},
        {"prospect_id": "p1", "score": 86, "qualified": True, "reasons": ["Matches the reference target."]},
        {"prospect_id": "p1", "trigger": case["hook"], "pain_hypothesis": "Unknown",
         "value_proposition": "Discuss the opportunity", "personalization_hook": case["hook"], "call_to_action": "Have a conversation"},
        {"prospect_id": "p1", "subject": "A conversation", "body": f"I am interested in {case['hook']}. Would you be open to a conversation?"},
        {"prospect_id": "p1", "approved": True, "score": 0.9, "issues": []},
    ])


async def evaluate(*, live: bool = False) -> dict:
    cases = json.loads(Path(__file__).with_name("cases.json").read_text())
    results = []
    for case in cases:
        repository = Repository(create_database())
        client = scripted_client(case)
        @asynccontextmanager
        async def factory():
            yield client
        settings = (Settings.from_env().model_copy(update={"checkpoint_backend": "memory"})
                    if live else Settings(checkpoint_backend="memory"))
        manager = RunManager(repository, InMemorySaver(), settings=settings,
                             client_factory=None if live else factory)
        started = time.monotonic()
        try:
            response = await manager.start(case_request(case))
            scores = score_run(response.state, case)
            record = repository.run(response.state.run_id)
            results.append({"case": case["name"], "scores": scores, "seconds": time.monotonic() - started,
                            "model_calls": record["model_calls"], "estimated_cost": record["estimated_cost"],
                            "failures": response.state.failures})
        finally:
            repository.engine.dispose()
    return {"mode": "live_model" if live else "simulation", "results": results,
            "note": "Simulation measures code and scoring behavior. Live results measure this configured model on these examples; subtle factual and tone quality still need human assessment."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = asyncio.run(evaluate(live=args.live))
    content = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content + "\n")
    print(content)


if __name__ == "__main__":
    main()
