# Outreach Agent

Phases one and two provide the foundation and structured records for a goal-driven outreach application. Submit an outreach goal, and the application validates it, creates a separate record for the request, and returns that record through the workflow coordinator.

The status `skeleton_ready` means this request path is working. Result collections are empty because research, qualification, and the other outreach steps belong to later phases.

## Set up the project

Use Python 3.12 or newer. Run the following commands from the project root. If you use a newer Python version, replace `python3.12` with that version's executable.

```bash
python3.12 --version
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

The virtual environment keeps the project's packages separate from your other projects. Installation includes FastAPI, Pydantic 2, Uvicorn, pytest, and HTTPX. Application startup and tests require no external-service credentials.

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
  "current_step": "skeleton_ready"
}
```

The request must contain exactly one field, `goal`, whose value is text. Leading and trailing whitespace is removed before checking the length. The remaining goal must contain between 1 and 2,000 characters. Capitalization and internal spacing are preserved.

Missing goals, blank goals, values that are not text, goals longer than 2,000 characters, and extra fields receive HTTP `422` with FastAPI's standard validation details. These requests stop before the workflow runs.

For example:

```bash
curl -i -X POST http://127.0.0.1:8000/outreach \
  -H 'Content-Type: application/json' \
  -d '{"goal":"   "}'
```

## How a request moves through the application

`app/main.py` creates the FastAPI application and registers the outreach endpoint. Uvicorn loads that application and serves requests. FastAPI checks each outreach request using `OutreachRequest` before calling the endpoint, which creates an `OutreachState` and passes it to `run_workflow` in `app/orchestration/workflow.py`.

The state starts with the goal, empty result collections, and the progress value `initialized`. The coordinator preserves that information and changes progress to `skeleton_ready` before returning it. Each request has its own state and collections; the application does not save them to a database.

The API returns the coordinator's result using `OutreachState` as its documented response format.

## Understand the files

The main distinction is between a format, a record, and a coordinator. `schemas.py` defines the format of each kind of information. `state.py` holds one request's goal, progress, and results together. `workflow.py` coordinates the steps that process that request.

| File | What it means |
|---|---|
| `app/main.py` | Creates the web application and connects its endpoints. Uvicorn loads the `app` object in this file when the server starts. |
| `app/api/outreach.py` | Defines `POST /outreach`. Receives a validated goal, creates a fresh state, waits for the workflow, and returns the result. |
| `app/models/schemas.py` | Defines the request and the five structured result formats, including rules for required text, scores, and decisions. |
| `app/orchestration/state.py` | Defines the record for one request. Keeps the goal, researched prospects, qualification results, selected prospects, strategies, drafts, reviews, and progress together. |
| `app/orchestration/workflow.py` | Coordinates the work. Currently sets progress to `skeleton_ready`; later phases will add research and qualification here. |
| `app/__init__.py` | Makes `app` a Python package whose modules can be imported. |
| `app/api/__init__.py` | Organizes the endpoint modules into the `app.api` package. |
| `app/models/__init__.py` | Organizes the data definitions into the `app.models` package. |
| `app/orchestration/__init__.py` | Organizes state and workflow code into the `app.orchestration` package. |
| `pyproject.toml` | Lists project details, required packages, installation settings, and pytest settings. |
| `.gitignore` | Tells Git to ignore the local Python environment and generated files. |
| `README.md` | Explains how to install, run, test, and understand the application. |
| `plan.md` | Records the phased implementation plan, completed checks, and next step. |

The files in `tests/` check the application using example data:

| File | What it checks or provides |
|---|---|
| `tests/conftest.py` | Provides fresh example records and a populated state to tests. pytest discovers these shared fixtures automatically. |
| `tests/test_schemas.py` | Checks valid and invalid input, required fields, score limits, decisions, independent default lists, and JSON conversion. |
| `tests/test_state.py` | Checks starting state, separate collections for each request, nested record types, and complete state conversion to and from JSON. |
| `tests/test_workflow.py` | Checks progress updates and preservation of the goal and existing results. |
| `tests/test_outreach_api.py` | Checks the complete request/response path, rejected requests, state isolation, and API documentation using a simulated HTTP client. |

Start with `app/api/outreach.py` to follow one request. Read `state.py` and `workflow.py` next. Keep `schemas.py` open to see the formats used by those files.

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
| `Literal["initialized", "skeleton_ready"]` | Describe the allowed progress labels when the state is validated. |
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

## Run the tests

With the virtual environment active:

```bash
python -m pytest
```

Tests cover goal validation, required result fields, score limits, independent collections, nested JSON conversion, preservation of workflow results, the API's response format, and API documentation. They run locally without calling external services. The API tests substitute a fake workflow when checking coordination and rejected requests.

## Next phase

Phase three will add one shared interface for structured model calls that can be replaced with a fake in tests. Research, search, qualification, memory, database storage, email writing, approvals, and Gmail integration follow in their specified phases.
