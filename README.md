# Outreach Agent

Phases one through four provide the application foundation, structured records, a shared model client, LangGraph orchestration, and a research component. Submit an outreach goal and optional research material, and the application returns its workflow state with any researched prospects.

The graph now runs `START → research → END`. The status `research_complete` means the research step finished. It can have zero prospects. Until search is added in phase five, the researcher uses only material you supply; a goal without material makes no model call and returns empty results.

## Set up the project

Use Python 3.12 or newer. Run the following commands from the project root. If you use a newer Python version, replace `python3.12` with that version's executable.

```bash
python3.12 --version
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

The virtual environment keeps the project's packages separate from your other projects. Installation includes FastAPI, Pydantic 2, Uvicorn, the OpenAI SDK, LangGraph, pytest, and HTTPX. Startup, goal-only requests, and tests require no external-service credentials. Requests with nonblank research material use the configured OpenAI client; its settings are explained below.

If you already installed an earlier phase, activate `.venv` and rerun `python -m pip install -e '.[dev]'` to install LangGraph. Startup commands and environment settings stay the same.

## Run the application

With the virtual environment active, start the local development server:

```bash
python -m uvicorn app.main:app --reload
```

Open [the API documentation](http://127.0.0.1:8000/docs) to view the endpoint and try a request. The generated API specification is at `/openapi.json`.

## Submit a goal

From another terminal, run:

```bash
curl -X POST http://127.0.0.1:8000/outreach \
  -H 'Content-Type: application/json' \
  -d '{"goal":"Find AI startups that may need our API observability product"}'
```

A successful request returns HTTP `200` and:

```json
{
  "goal": "Find AI startups that may need our API observability product",
  "prospects": [],
  "qualification_results": [],
  "qualified_prospects": [],
  "strategies": {},
  "drafts": {},
  "reviews": {},
  "current_step": "research_complete"
}
```

The required field, `goal`, must be text. Leading and trailing whitespace is removed before checking the length. The remaining goal must contain between 1 and 2,000 characters. Capitalization and internal spacing are preserved. You can also supply `research_material` as text containing notes and their source references. Its formatting is preserved; omitted or blank material makes no model call.

Missing goals, blank goals, incorrectly typed goals or material, goals longer than 2,000 characters, and unrecognized fields receive HTTP `422` with FastAPI's standard validation details. These requests stop before model creation or workflow execution.

For example:

```bash
curl -i -X POST http://127.0.0.1:8000/outreach \
  -H 'Content-Type: application/json' \
  -d '{"goal":"   "}'
```

## Supply research material

After exporting `OPENAI_API_KEY` and `OPENAI_MODEL` as described below, you can submit notes along with the goal. This request makes a real model call:

```bash
curl -X POST http://127.0.0.1:8000/outreach \
  -H 'Content-Type: application/json' \
  -d '{
    "goal": "Find professors researching wearable AI for PhD outreach.",
    "research_material": "Source: https://example.com/lab\nExample University. Professor Ada Lin researches wearable AI."
  }'
```

These are illustrative names and a placeholder URL. Replace them with your own evidence. Returned prospects use the existing `Prospect` fields, including `company_name` for the organization and `decision_maker_name` for the person. Unknown optional information stays `null`.

The researcher requests only facts supported by the supplied material. It checks that IDs are distinct, organization and person names occur in the material, and each prospect has source references present in that material. These are basic checks; they do not verify a website or prove that every generated statement is accurate. Review the returned research before using it for outreach.

Missing model settings return HTTP `503`. Model request failures, refusals, malformed output, and failed evidence checks return HTTP `502` with a short error message. Qualification, strategies, email drafts, and reviews remain empty for new requests in this phase.

### Try the complete research workflow without credentials

This example runs the real graph with a preset model response. It checks the application path; the fake does not perform research:

```bash
python - <<'PY'
import asyncio

from app.agents.researcher import Researcher
from app.models.client import FakeModelClient
from app.orchestration.state import OutreachState
from app.orchestration.workflow import run_workflow

async def main():
    material = (
        "Source: https://example.com/lab\n"
        "Example University. Professor Ada Lin researches wearable AI."
    )
    client = FakeModelClient([{"prospects": [{
        "id": "p1",
        "company_name": "Example University",
        "decision_maker_name": "Ada Lin",
        "decision_maker_role": "Professor",
        "signals": ["Wearable AI research"],
        "sources": ["https://example.com/lab"],
    }]}])
    state = OutreachState(goal="Find professors researching wearable AI for PhD outreach.")
    result = await run_workflow(
        state, researcher=Researcher(client=client), research_material=material,
    )
    print(result.model_dump_json(indent=2))

asyncio.run(main())
PY
```

## How a request moves through the application

`app/main.py` creates the FastAPI application and registers the outreach endpoint. Uvicorn loads that application and serves requests. FastAPI checks each outreach request using `OutreachRequest` before calling the endpoint, which creates an `OutreachState` and passes it to `run_workflow` in `app/orchestration/workflow.py`.

The state starts with the goal, empty result collections, and the progress value `initialized`. For requests with material, a FastAPI dependency provides an OpenAI client and closes it after the request. Tests can replace that dependency with a fake. This follows FastAPI's [dependency cleanup](https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-with-yield/) and [dependency override](https://fastapi.tiangolo.com/advanced/testing-dependencies/) patterns.

The coordinator invokes the compiled graph in `app/orchestration/graph.py`. Its execution path is `START → research → END`. The research node calls the `Researcher` component, which uses `generate_structured` to obtain a `ResearchResult` containing typed `Prospect` records. The node returns partial updates for prospects and progress. Without new material, it preserves any prospects already in the supplied state and updates only progress.

LangGraph returns a dictionary. `run_workflow` validates it as `OutreachState`, copies the resulting fields into the supplied record, and returns that same record. The API continues using its existing workflow function and response format. The graph is compiled once; each request has its own state. No checkpointing or database storage is configured.

The implementation follows the [LangGraph Graph API documentation](https://docs.langchain.com/oss/python/langgraph/use-graph-api). The researcher and material travel through per-request runtime context, separate from the result state. The graph owns execution, the researcher owns research logic, and the existing model client owns provider access.

The API returns the coordinator's result using `OutreachState` as its documented response format.

## Understand the files

The main distinction is between a format, a record, and an execution path. `schemas.py` defines the format of each kind of information. `state.py` holds one request's goal, progress, and results together. `graph.py` defines which workflow steps run, and `workflow.py` connects the application to that graph. `client.py` provides the shared way for future components to request model output in a specified format.

For the complete file-by-file explanation, read [FILE_GUIDE.md](FILE_GUIDE.md).

| File | What it means |
|---|---|
| `app/main.py` | Creates the web application and connects its endpoints. Uvicorn loads the `app` object in this file when the server starts. |
| `app/api/outreach.py` | Defines `POST /outreach`. Receives a validated goal, creates a fresh state, waits for the workflow, and returns the result. |
| `app/models/schemas.py` | Defines the request and the five structured result formats, including rules for required text, scores, and decisions. |
| `app/models/client.py` | Requests model output, checks it against the chosen record format, and provides real and fake clients. |
| `app/agents/researcher.py` | Turns supplied material into typed prospects and checks names, source references, and distinct IDs. |
| `app/prompts/researcher.py` | Holds the instructions for evidence-based research across different outreach goals. |
| `app/orchestration/nodes/research.py` | Passes the goal and per-request material to the researcher and returns partial graph updates. |
| `app/orchestration/state.py` | Defines the record for one request. Keeps the goal, researched prospects, qualification results, selected prospects, strategies, drafts, reviews, and progress together. |
| `app/orchestration/graph.py` | Builds and compiles `START → research → END` using `OutreachState` and `ResearchContext`. |
| `app/orchestration/workflow.py` | Provides the existing `run_workflow(state)` interface. Invokes the graph, validates its output, and updates and returns the supplied record. |
| `app/__init__.py` | Makes `app` a Python package whose modules can be imported. |
| `app/api/__init__.py` | Organizes the endpoint modules into the `app.api` package. |
| `app/models/__init__.py` | Organizes the data definitions into the `app.models` package. |
| `app/orchestration/__init__.py` | Organizes state and workflow code into the `app.orchestration` package. |
| `pyproject.toml` | Lists project details, required packages, installation settings, and pytest settings. |
| `.env.example` | Provides the names of optional model settings; it contains no credentials. |
| `.gitignore` | Tells Git to ignore the local Python environment, local credentials, and generated files. |
| `README.md` | Explains how to install, run, test, and understand the application. |
| `plan.md` | Records the phased implementation plan, completed checks, and next step. |

The files in `tests/` check the application using example data:

| File | What it checks or provides |
|---|---|
| `tests/conftest.py` | Provides fresh example records and a populated state to tests. pytest discovers these shared fixtures automatically. |
| `tests/test_schemas.py` | Checks valid and invalid input, required fields, score limits, decisions, independent default lists, and JSON conversion. |
| `tests/test_client.py` | Checks preset model responses, output validation, OpenAI request formatting and parsing, failures, and connection cleanup without external calls. |
| `tests/test_researcher.py` | Checks typed prospects, different goals, supplied evidence, invalid output, missing material, and model errors using fake clients. |
| `tests/test_research_node.py` | Checks that the node calls the component, updates only research fields, and propagates errors without mutating input state. |
| `tests/test_state.py` | Checks starting state, separate collections for each request, nested record types, and complete state conversion to and from JSON. |
| `tests/test_graph.py` | Checks compilation, the execution path, progress updates, preserved records, goal validation, and separate state for concurrent requests. |
| `tests/test_workflow.py` | Checks delegation to the graph, typed output, preservation of the supplied record, and behavior when the graph fails or returns invalid output. |
| `tests/test_outreach_api.py` | Checks the complete request/response path, rejected requests, state isolation, and API documentation using a simulated HTTP client. |

Start with `app/api/outreach.py` to follow one request. Read `state.py`, `workflow.py`, and `graph.py` next. Keep `schemas.py` open to see the formats used by those files.

## Understand common code patterns

| Code | Plain-language meaning |
|---|---|
| `from ... import ...` | Bring a class or function from another module into this file. |
| `class Prospect(BaseModel)` | Define a structured record whose incoming data Pydantic validates. |
| `goal: GoalText` | Define a field named `goal` that follows the shared goal-validation rules. |
| `Annotated[str, ...]` | Combine the text type with extra validation rules. |
| `ConfigDict(extra="forbid")` | Reject fields the record does not recognize. |
| `NonEmptyText \| None = None` | Allow either valid text or an unknown value; omitted values default to `None`. |
| `Field(default_factory=list)` | Create a fresh empty list for every new record. |
| `dict[str, EmailDraft]` | Store drafts under text keys, such as a prospect ID. |
| `Literal["initialized", "skeleton_ready", "research_complete"]` | Describe the allowed progress labels, including the earlier foundation label. |
| `async def` and `await` | Define an asynchronous function and wait for another asynchronous function's result. The endpoint waits for the workflow before returning. |
| `model_dump()` and `model_dump_json()` | Convert a record into a Python dictionary or JSON text, respectively. |
| `@pytest.fixture` | Define example data or a helper that pytest supplies to tests requesting it by name. |
| `@pytest.mark.parametrize` | Run one test with several different examples. |
| `assert` | Check that a result matches an expectation; a mismatch fails the test. |

## Structured results

Phase two defines five records in `app/models/schemas.py`. Future workflow components will use these records to pass information to one another.

| Record | Information it holds |
|---|---|
| `Prospect` | Company ID and name, optional website and industry, optional decision-maker details, signals, and source references |
| `Qualification` | Prospect ID, score from 0–100, qualification decision, and reasons |
| `OutreachStrategy` | Prospect ID, trigger, pain hypothesis, value proposition, personalization hook, and call to action |
| `EmailDraft` | Prospect ID, subject, and body |
| `ReviewResult` | Prospect ID, the reviewer's approval decision, score, and issues |

Unknown company and decision-maker details can be omitted or set to `null`. Required text must contain more than whitespace. Lists of signals, sources, reasons, and issues start empty when omitted, and each record gets its own lists. Unexpected fields are rejected.

Qualification scores must be whole numbers from 0 through 100. Qualification and review decisions must be actual booleans. Review scores must be finite numbers; their scale will be defined when the reviewer is implemented. Email body formatting is preserved. Website and source references are stored as strings.

`OutreachState` now uses these records for its result collections. `qualification_results` retains scores and explanations separately from the selected `qualified_prospects`. Strategies, drafts, and reviews are dictionaries keyed by prospect ID. These formats are included in the API documentation.

Phase four adds `ResearchResult`, a wrapper containing a list of existing `Prospect` records. It is the format requested from the model and introduces no replacement for the five domain records.

## Shared model calls

Phase three adds `generate_structured` in `app/models/client.py`. The researcher and future agents use this function whenever they need a model to produce a record. You supply the task instructions, the information to process, the expected record class, and the client to use. The function returns a validated instance of that class.

`FakeModelClient` returns responses you provide in advance, in order. It is useful for learning and testing because the results are repeatable. With the virtual environment active, run this example from the project root:

```bash
python - <<'PY'
import asyncio

from app.models.client import FakeModelClient, generate_structured
from app.models.schemas import Qualification

async def main():
    client = FakeModelClient([
        {
            "prospect_id": "p1",
            "score": 86,
            "qualified": True,
            "reasons": ["The company is expanding its API infrastructure."],
        }
    ])
    result = await generate_structured(
        instructions="Return a qualification record for this company.",
        input_text="Example AI is expanding its API infrastructure.",
        response_model=Qualification,
        client=client,
    )
    print(result.model_dump_json(indent=2))

asyncio.run(main())
PY
```

The example prints the preset qualification record. The fake does not analyze the input. A malformed preset response fails the same record validation as a real model response. `client.calls` records the supplied prompts and record classes so tests can inspect them.

### Optional OpenAI configuration

`OpenAIModelClient` uses the async Responses API with [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs). It builds the requested output format from your Pydantic class. Choose a model available to your account that supports this feature.

When you are ready to call a real model, copy `.env.example` to `.env`, fill in `OPENAI_API_KEY` and `OPENAI_MODEL` locally, and export those settings into your terminal:

```bash
cp .env.example .env
# Edit .env before running the following lines.
set -a
source .env
set +a
```

The application does not load `.env` automatically. The file is ignored by Git. The endpoint creates an OpenAI client when nonblank research material is supplied. Goal-only requests and fake-client examples need no settings.

Inside an asynchronous function, replace the fake client with this pattern:

```python
from app.models.client import OpenAIModelClient, generate_structured
from app.models.schemas import Qualification

async def qualify_company(company_notes):
    async with OpenAIModelClient.from_env() as client:
        return await generate_structured(
            instructions="Assess this company and return a qualification record.",
            input_text=company_notes,
            response_model=Qualification,
            client=client,
        )
```

The context closes the connection when the work finishes. Real requests use your OpenAI account. The client reports provider request failures as `ModelClientError`, missing or invalid output as `ModelResponseError`, and refusals as `ModelRefusalError`. These classes share the `ModelClientError` base so a future caller can handle them together when appropriate.

`POST /outreach` now returns `research_complete` after the research node finishes. The researcher uses this shared model boundary; later agents will use it too.

## Run the tests

With the virtual environment active:

```bash
python -m pytest
```

Tests cover goal validation, required result fields, score limits, independent collections, nested JSON conversion, preservation of workflow results, the API's response format, API documentation, structured model calls, and LangGraph execution. They run locally without calling external services. The graph tests use the actual local LangGraph runtime. API tests check both the real graph path and replacement workflows when checking coordination and rejected requests. The OpenAI client tests use the actual SDK with an HTTPX mock transport that supplies every response locally.

## Next phase

Phase five will add an injectable search tool with typed results and source references. Qualification follows in phase six and conditional routing in phase seven. Later phases add structured goal interpretation, relationship memory, contact policy, writing, review, human approval, and Gmail capabilities.
