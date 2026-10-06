# Outreach Agent

The application now supports a complete outreach workflow: interpret your goal, research prospects, qualify them, check relationship history and contact rules, prepare and review drafts, and pause for your decision. Saved runs can resume after approval or editing. Gmail reading, draft creation, and guarded sending use replaceable adapters.

**V1 uses the CLI: run `python -m app.cli`.** It asks ordinary questions in your terminal, runs the complete workflow, and lets you inspect saved results and approve, reject, or edit drafts. No HTTP server is needed for the CLI. Web UI, Telegram, and WhatsApp work are deferred.

The optional API remains available: `POST /runs` runs the complete workflow, and `POST /outreach` handles research-only requests. Its `research_complete` status means that research finished and may have zero prospects. A research-only goal without material still makes no model call.

For an interactive example without credentials, run `python -m app.cli --demo`. The earlier `python -m app.demo` automated example also remains available. [FILE_GUIDE.md](FILE_GUIDE.md) explains every file and what we added in each phase. [plan.md](plan.md) records the implementation and verification through phase 30 and the V1 interface work.

Groq is supported for your model calls. The [Groq setup](#groq-setup-and-the-keys-you-need) below explains the keys and how to start it. The CLI and optional API share the same workflow and database records.

## Set up the project

Use Python 3.12 or newer. Run the following commands from the project root. If you use a newer Python version, replace `python3.12` with that version's executable.

```bash
python3.12 --version
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

The virtual environment keeps the project's packages separate from your other projects. Installation includes FastAPI, Pydantic 2, Uvicorn, the OpenAI SDK, LangGraph, HTTPX, SQLAlchemy, SQLite checkpoint support, and pytest. Startup, research-only goal requests, the demonstration, and normal tests require no external-service credentials. Real complete runs need the configured model; search and Gmail are optional.

If you installed an earlier phase, activate `.venv` and rerun `python -m pip install -e '.[dev]'` to install the added storage dependencies and register the `outreach` terminal command.

## Run the application

With the virtual environment active and your settings exported, run:

```bash
python -m app.cli
```

You can also use `outreach` after installing the project. The menu lets you:

- Start a goal by entering your background, research notes or web-search choice, and known recipient addresses.
- List saved runs and inspect their prospects, drafts, outcomes, or execution events.
- Review a paused run and approve, reject, or edit each message. The CLI handles draft identifiers and versions for you.
- Retry a failed run from saved progress, or check which credentials are configured.

For recipients, enter a target's exact display name from your evidence, or its known prospect ID. The researcher does not discover email addresses automatically. The initial action choices are `none` for recording the approved result, or `draft` for approved Gmail draft creation. Starting a run never approves it automatically. Choosing `later` while reviewing leaves all decisions unsubmitted; edits return for review and fresh approval within the existing revision limit.

Paused real runs survive exit/restart using SQLite. The run list shows up to 100 records sorted by identifier; copy an ID when reviewing an older run. Press Enter at a run-ID prompt to use the most recently accessed run in the current session. Ctrl+C interrupts active work; interrupted workflow execution is marked failed and can be inspected or retried within its existing budgets. A hard process kill may still require waiting for its run lease to expire.

To check configuration without contacting any provider:

```bash
python -m app.cli --check-config
```

This prints **configured/MISSING**, never key values. It checks setting presence, not whether a provider accepts the credentials. Exit code `0` means the selected model settings are present, and `1` means they are missing or configuration is invalid. Brave and Gmail remain optional. A real goal run tests model access; selecting search or approving a Gmail draft exercises those optional integrations.

The optional HTTP server is still available for development or other programs:

```bash
python -m uvicorn app.main:app --reload
```

Open [the API documentation](http://127.0.0.1:8000/docs) to view the endpoint and try a request. The generated API specification is at `/openapi.json`.

## Try the complete workflow without credentials

Try the interactive CLI first:

```bash
python -m app.cli --demo
```

Choose `1` to start the fictional PhD outreach example, then `4` to review it. Press Enter for the latest run ID and type `approve` to record a fake Gmail draft. The demo never contacts providers and its temporary records disappear on exit.

The automated example uses the same fictional records and fake clients, including a fake Gmail tool. It creates no real Gmail drafts or emails:

```bash
python -m app.demo
```

Expected output includes `awaiting_approval`, followed by `drafted` after the demonstration's simulated approval. To try the same simulation through HTTP, start a separate local server:

```bash
python -m uvicorn app.demo:app --port 8001
```

Open [the demo API documentation](http://127.0.0.1:8001/docs), or submit the example below to port `8001`. Use `gmail_action="draft"` with a sender email to exercise fake draft creation. The demo is a control-flow example; it does not measure a real model's understanding or research quality.

## Define your goal and start a complete run

In the CLI, choose `1` and enter your goal when asked. You do not need to edit a Python file. Examples include finding a PhD supervisor, finding founders hiring engineers, researching potential customers, and identifying collaboration partners. For API callers the same text belongs in the request's **`goal` field**.

For the real server on port `8000`, configure Groq as described below, or explicitly select the OpenAI alternative. This request uses your selected model and supplied evidence but performs no Gmail action:

```bash
curl -X POST http://127.0.0.1:8000/runs \
  -H 'Content-Type: application/json' \
  -d '{
    "goal": "Find professors studying AI observability for PhD outreach.",
    "research_material": "Example University. Ada Example studies AI observability. Source: https://example.com/lab",
    "sender": {"name": "Example Student", "email": "student@example.com", "context": "I am exploring PhD supervision."},
    "recipients": {"Example University": {"email": "professor@example.com", "source": "Address supplied by the user for this example"}},
    "use_search": false,
    "gmail_action": "none"
  }'
```

HTTP `201` means the run was created. Its response contains `state`, `awaiting_approval`, and any execution error. The state includes a `run_id`, interpreted goal, prospects, qualification reasons, memories, contact decisions, strategies, drafts, reviews, and outcomes.

Recipient mappings may use the prospect ID or exact target display name. Addresses are explicitly supplied rather than guessed. Without an address the application can research and qualify a prospect, but contact rules block further outreach for that prospect. `sender.context` supplies your actual background or product details for the message.

Set `use_search=true` to use Brave results instead of, or alongside, supplied notes. This needs `BRAVE_SEARCH_API_KEY`. The researcher preserves URLs and checks names/references against the evidence; snippets and these checks do not independently prove every claim.

The normal result may pause with `current_step="awaiting_approval"`. Read each entry in `state.approval_requests`: it contains the prospect, recipient, evidence, memories, strategy, draft, version, and `fingerprint`, a hash binding the decision to that exact content. Read a saved run with `GET /runs/{run_id}`.

## Approve, reject, or edit a paused run

In `/docs`, call `POST /runs/{run_id}/decisions` using the saved identifier. Supply exactly one decision for each pending draft. Copy its prospect ID, version, and fingerprint from the current response:

```json
{
  "decisions": [
    {
      "prospect_id": "p1",
      "version": 1,
      "fingerprint": "COPY_THE_CURRENT_FINGERPRINT",
      "action": "approve"
    }
  ]
}
```

Use `action="reject"` to end that prospect's processing. Use `action="edit"` with an `edited_draft` containing the same `prospect_id`, a new `subject`, and `body`. Edits consume the revision allowance, remove the old review/approval, and return the new content for review and a fresh decision. The initial allowance is one revision, shared with automatic rewrites. Exhausting it produces `manual_review`.

Approval resumes the existing execution. It does not repeat the research or create a new run. With `gmail_action="none"`, approval records the outcome and finishes without contacting Gmail. With `"draft"`, it may create a Gmail draft after another contact-policy check. `"send"` additionally requires explicit server enablement, described below.

Inspect `outcomes` and `failures` even when a run is completed: completion means processing ended, and a prospect may have been blocked, rejected, or failed. Failed invocations return a `run_id` where available, so you can inspect `GET /runs/{run_id}/events` and use `POST /runs/{run_id}/retry` after fixing the cause. Retry keeps the same budgets and does not blindly repeat an uncertain Gmail action.

## Relationship memory and replies

Local relationship records are saved in `.data/relationships.sqlite3`. Execution checkpoints are saved separately in `.data/checkpoints.sqlite3`, so a real paused run can survive restarting the application. The separate demo uses memory-only storage. Both local files contain private application data and are ignored by Git.

**V1 database: SQLite, accessed through SQLAlchemy.** SQLite stores information in ordinary local files, so you need no database account, server, password, or API key. Relationship data includes contact history, remembered facts, outcomes, run summaries, and action records. Checkpoints hold the saved progress needed to resume one workflow. The CLI and API use these same files when launched from the same project folder with the same settings. PostgreSQL support remains an optional later deployment choice.

`GET /contacts/{email}` shows sourced facts, interaction history, contact rules, consolidated duplicates, and possible conflicts. To process a received reply, submit its text and source:

```json
{
  "contact_email": "professor@example.com",
  "source": "gmail:YOUR_MESSAGE_ID",
  "body": "Please reconnect on 2027-02-01."
}
```

Send this to `POST /replies`. Processing classifies the reply, extracts exact supporting quotes, and updates relationship context. Explicit unsubscribe phrases block future outreach before a model call. Ordinary reply processing cannot clear an opt-out. A reconnect date is used automatically only when it is explicitly written as an ISO date; other timing language remains available for human interpretation. No automatic follow-up email is created.

Ordinary reply processing marks the conversation active, so it does not trigger new cold outreach. Use `PUT /contacts/{email}/policy` for a sourced manual change to `active_conversation` or a timezone-qualified `reconnect_at` when the conversation or timing changes. This endpoint cannot remove an opt-out. Recording what happened is different from saving a workflow checkpoint: relationship memory is shared across future requests, while a checkpoint resumes one execution.

## Groq setup and the keys you need

For a real run with supplied research notes, you need a **Groq API key**. Create it in your [Groq console](https://console.groq.com/keys). Add Brave if you want the application to search the web, and Gmail access if you want mailbox history or Gmail actions.

| Credential | What we use it for | When you need it |
|---|---|---|
| `GROQ_API_KEY` | Goal interpretation, research, qualification, strategy, writing, review, and ordinary reply processing. | Real Groq model calls. |
| `BRAVE_SEARCH_API_KEY` | Find web evidence and source URLs. | Runs with `use_search=true`; supplied notes can be used instead. |
| `GMAIL_ACCESS_TOKEN` | Read relevant Gmail conversations and create approved drafts or send enabled messages. | Gmail features; obtained through Google OAuth. This implementation accepts an access token and needs manual renewal. |
| `OUTREACH_API_KEY` | Protect access to the optional HTTP API. You choose this secret; a model provider does not issue it. | Sharing or hosting the API; the local CLI needs no API key. |
| PostgreSQL connection credentials | Access a separately hosted database. | Optional PostgreSQL setup; local SQLite needs no database account. |

`OUTREACH_MODEL_PROVIDER` and `GROQ_MODEL` are settings, not secret keys. The template selects `groq` and uses `openai/gpt-oss-120b`, a model hosted by Groq. The `openai/` prefix is part of that model's name; Groq handles the request and billing, using your Groq key. An OpenAI key is only used when you select `openai` as the provider.

The Groq adapter requests JSON schema output in best-effort mode because the existing records contain optional fields. It validates every returned record before the workflow uses it. Choose a model from Groq's [Structured Outputs model list](https://console.groq.com/docs/structured-outputs); the configured example is listed there. The adapter has been checked with local HTTP responses, not a live Groq account.

From the project directory:

```bash
source .venv/bin/activate
cp -n .env.example .env
# Edit .env locally: fill GROQ_API_KEY and any optional credentials you need.
set -a
source .env
set +a
python -m app.cli --check-config
python -m app.cli
```

Use the terminal menu to supply your goal, sender information, recipient email addresses, and research notes or web search. Start with `none` to review the complete path, or `draft` after configuring Gmail. The review menu submits the exact current draft decision for you. Sending remains disabled by default. If you use the optional server, its [documentation page](http://127.0.0.1:8000/docs) exposes the same request and decision operations.

For Google OAuth setup, you may need a Google Cloud OAuth client ID and client secret to obtain the Gmail token. Those are setup credentials; this application's current runtime reads `GMAIL_ACCESS_TOKEN`. Automatic login and refresh-token management would be additional work.

## Web UI, Telegram, or WhatsApp

**V1 is the CLI.** It runs the backend directly while the terminal session is open, and saves paused work to SQLite. The optional API and `/docs` remain useful for developers. A custom web UI, Telegram bot, and WhatsApp adapter are deferred until we have tried real goals and configured integrations through the CLI.

The following options describe possible later interfaces. They would reuse the existing workflow and its approval rules:

| Interface | How it would work | Additional setup | Current status |
|---|---|---|---|
| CLI | Enter goals and review results through a terminal menu. | Run `python -m app.cli`; configure keys for real calls. | Implemented; V1 interface. |
| Web UI | Enter a goal, follow saved runs, inspect prospects and drafts, approve/edit/reject. | Build browser screens connected to the existing API. | Deferred beyond V1. |
| Telegram | Message your bot with a goal and receive status updates or approval controls. | A BotFather bot token and an allowed owner/user ID. Long polling can run on your computer; webhook delivery uses a public HTTPS endpoint. | Proposed; no Telegram code or environment settings exist yet. |
| WhatsApp | Message a business number connected to a webhook that forwards commands to this backend. | Meta business app/WhatsApp setup, access token, phone-number and business-account IDs, an app secret for webhook signatures, a chosen verification token, and a public HTTPS endpoint. | Proposed; no WhatsApp code or environment settings exist yet. |

Telegram's [BotFather instructions](https://core.telegram.org/bots/features#botfather) and [Bot API](https://core.telegram.org/bots/api) document its token and update delivery. Meta's [official WhatsApp example](https://github.com/fbsamples/whatsapp-api-examples/tree/main/template-for-ecommerce-js) shows the account settings, message requests, and signed/verified webhook pattern.

Telegram or WhatsApp can become ways for **you** to control the email workflow from your phone. The existing outreach channel is Gmail. Contacting prospects directly through Telegram or WhatsApp would require a separate outreach adapter and its own approval/contact rules. Keeping the backend on a server would allow continuous use; on your laptop it runs while the application process is running.

## Search, Gmail, PostgreSQL, and operating settings

Copy `.env.example` for reference and **explicitly export** the settings you need. Copying it does not load the file. Restart the CLI or optional server after changing its configuration.

| Setting | What it controls |
|---|---|
| `OUTREACH_MODEL_PROVIDER` | `groq` for your setup, or `openai` for the original adapter. Existing installations without this setting continue using OpenAI. |
| `GROQ_API_KEY`, `GROQ_MODEL` | Groq model access and model name. The example model supports JSON schema output. |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | Optional alternative when the provider is `openai`; choose a compatible model available to your account. |
| `BRAVE_SEARCH_API_KEY` | Optional Brave web search for `use_search=true`. |
| `GMAIL_ACCESS_TOKEN` | A valid OAuth access token for your own Gmail account. Renew it when it expires; automatic token refresh/login is not included. |
| `OUTREACH_READ_GMAIL=true` | Read relevant Gmail threads during the memory check. Default: false. |
| `OUTREACH_ENABLE_SENDING=true` | Explicitly enable the guarded sending capability. Default: false. A send still requires `gmail_action="send"`, current human approval, valid recipient, allowed contact policy, and a unique action. |
| `OUTREACH_DATA_DIR` | Local data location. Default: `.data`. |
| `OUTREACH_DATABASE_URL` | Optional SQLAlchemy database URL; otherwise SQLite is used. PostgreSQL uses `postgresql+psycopg://...`. |
| `OUTREACH_CHECKPOINT_BACKEND` | `sqlite` by default, or `memory` for temporary runs, or `postgres`. |
| `OUTREACH_CHECKPOINT_POSTGRES_URL` | PostgreSQL connection URI for the optional checkpointer, using `postgresql://...`. |
| `OUTREACH_API_KEY` | Protect the single-account API using the `X-API-Key` header. Set this before sharing/deploying the application. |
| `OUTREACH_LIMITS_JSON` | Optional JSON overrides for the limits in `app/security/limits.py`. |

For Gmail, enable the Gmail API in your Google Cloud project and obtain an OAuth token with the permissions needed for the chosen action. Reading threads uses `gmail.readonly`; draft creation uses `gmail.compose`; sending needs a scope permitting send, such as `gmail.send` or `gmail.compose`. See Google's [scope definitions](https://developers.google.com/workspace/gmail/api/auth/scopes) and [OAuth setup](https://developers.google.com/workspace/gmail/api/auth/web-server). The adapter uses your token and never starts an authorization flow on its own.

To install PostgreSQL support:

```bash
python -m pip install -e '.[dev,postgres]'
```

Configure the relationship database and checkpoint connection separately. Their initial tables are created during setup; future schema changes need explicit migrations. Local tests check portable table definitions and SQLite persistence. A real PostgreSQL server and account integrations need their own configured integration check before deployment.

Default limits include 10 discovered prospects, 5 qualified prospects, 2 search attempts, 40 model attempts, one revision, 100 graph steps, a 60-second model timeout, and one concurrent prospect operation. For example:

```bash
export OUTREACH_LIMITS_JSON='{"concurrency":2,"max_model_calls":30,"max_search_calls":2}'
```

Model attempts reserve a configured estimated cost before calling the provider, and those counters survive approval and retry. Adjust the estimate for your model and workload; it is not an exact billing cap. Returned token usage, when available, is recorded in execution events according to the [Responses API usage fields](https://developers.openai.com/api/reference/python/resources/responses/methods/create). The process request limiter is shared by this single account; multiple workers need an upstream/shared limiter.

Gmail writes are claimed in persistent action and contact records before the network call. A lost response produces an `uncertain` result and blocks blind retries; inspect Gmail and the action history before taking another action. Sending has not been enabled or exercised against a live account as part of this implementation.

## Research-only endpoint

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

After configuring Groq or the OpenAI alternative as described above, you can submit notes along with the goal. This request makes a real model call:

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

Missing model settings return HTTP `503`. Model request failures, refusals, malformed output, and failed evidence checks return HTTP `502` with a short error message. Qualification, strategies, email drafts, and reviews remain empty on this research-only endpoint; use `/runs` for those steps.

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

Phase two defines five records in `app/models/schemas.py`. The implemented components use these records to pass information to one another.

| Record | Information it holds |
|---|---|
| `Prospect` | Target ID/display name, organization/person type, optional website and industry, optional decision-maker details, signals, and source references |
| `Qualification` | Prospect ID, score from 0–100, qualification decision, and reasons |
| `OutreachStrategy` | Prospect ID, trigger, pain hypothesis, value proposition, personalization hook, and call to action |
| `EmailDraft` | Prospect ID, subject, and body |
| `ReviewResult` | Prospect ID, the reviewer's approval decision, score, and issues |

Unknown company and decision-maker details can be omitted or set to `null`. Required text must contain more than whitespace. Lists of signals, sources, reasons, and issues start empty when omitted, and each record gets its own lists. Unexpected fields are rejected.

Qualification scores must be whole numbers from 0 through 100. Qualification and review decisions must be actual booleans. The implemented reviewer uses scores from 0 to 1; the shared record still accepts finite scores from earlier formats. Email body formatting is preserved. Website and source references are stored as strings. For person-only outreach, `entity_type="person"` identifies the target and the legacy `company_name` field holds their supplied display name.

`OutreachState` now uses these records for its result collections. `qualification_results` retains scores and explanations separately from the selected `qualified_prospects`. Strategies, drafts, and reviews are dictionaries keyed by prospect ID. These formats are included in the API documentation.

Phase four adds `ResearchResult`, a wrapper containing a list of existing `Prospect` records. It is the format requested from the model and introduces no replacement for the five domain records.

## Shared model calls

Phase three adds `generate_structured` in `app/models/client.py`. The implemented reasoning components use this function whenever they need a model to produce a record. You supply the task instructions, the information to process, the expected record class, and the client to use. The function returns a validated instance of that class.

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

To choose this alternative, set `OUTREACH_MODEL_PROVIDER=openai`, fill in `OPENAI_API_KEY` and `OPENAI_MODEL` locally, and export those settings into your terminal:

```bash
cp -n .env.example .env
# Edit .env before running the following lines.
set -a
source .env
set +a
```

The application does not load `.env` automatically. The file is ignored by Git. The endpoint creates the client selected by `OUTREACH_MODEL_PROVIDER` when nonblank research material is supplied. Goal-only requests and fake-client examples need no settings.

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

## Run evaluations and refine the implementation

Run the local evaluation cases without credentials:

```bash
python -m evals.run --output .data/evaluations.json
```

The report labels this as `simulation`: it verifies the workflow and scoring on preset reference responses. It does not establish real model quality. `python -m evals.run --live` explicitly calls the configured model on the examples and can consume credits, while performing no Gmail actions. The checks measure target/reference agreement, sources, selections, memory, message constraints, and workflow rules; subtle factual accuracy and tone still need human assessment.

Optional model routing in `app/models/router.py` requires adequate recorded measurements for every configured route. No production model routes have been selected. Concurrent processing is available through limits after validating the individual flow. Advanced memory offers source-preserving consolidation and optional semantic retrieval with an injected embedding function and measured reason; no embedding provider or vector database is enabled by default.

The complete, revisable scope and verification through phase 30 are in [plan.md](plan.md#remaining-phases). [FILE_GUIDE.md](FILE_GUIDE.md#phases-5-to-30-add-the-complete-outreach-workflow) explains what was implemented and which files belong to each phase.
