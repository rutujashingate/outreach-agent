# API and Integration Guide

V1 is an interactive terminal application. This guide is for developers using the optional HTTP API, changing provider settings, or exploring the shared model client. Start with the [README](../README.md) for the product overview, diagrams, CLI setup, and SQLite explanation. The [file guide](../FILE_GUIDE.md) explains the implementation file by file.

## Start the optional API

Export your settings into the current terminal, activate the project's environment, and run:

```bash
python -m uvicorn app.main:app --reload
```

Open [the interactive API documentation](http://127.0.0.1:8000/docs). If `OUTREACH_API_KEY` is configured, add `X-API-Key` to API requests. CLI users do not need this key or server. The CLI and API use the same SQLite files when their working directory and settings match.

The examples below use fictional names and source URLs. Real requests with research material use your configured model. V1 defaults to SQLite for both relationship storage and saved workflow progress; the PostgreSQL instructions describe an optional deployment choice.

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

The context closes the connection when the work finishes. Real requests use your OpenAI account. The client reports provider request failures as `ModelClientError`, missing or invalid output as `ModelResponseError`, and refusals as `ModelRefusalError`. These classes share the `ModelClientError` base so callers can handle them together when appropriate.

`POST /outreach` returns `research_complete` after the research node finishes. The complete `/runs` workflow also uses the shared model client for goal interpretation, research, qualification, strategy, writing, and review.
