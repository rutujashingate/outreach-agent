# Outreach Agent Plan

Phase one builds the application foundation. Phase two gives workflow results a consistent format. Phase three provides one shared way to request structured model output. Phase 3.5 introduces LangGraph as the internal workflow engine. Phase four adds research from supplied material. These phases are implemented; their work and verification are recorded below.

## Product direction

The application will support goal-driven research and outreach informed by prior relationships. Goals can involve jobs, PhD opportunities, sales, networking, or partnerships. The user supplies a goal; later components will research relevant prospects and prepare grounded outreach for human review.

LangGraph owns execution order, state updates, and later routing. Application components own business logic. The existing `generate_structured` model client owns model access. Tools will handle external search and Gmail actions, and a database will hold durable relationship information in a later phase.

The current graph performs research using supplied material. Search, qualification, and later components and integrations remain planned.

## What we want to achieve

Build a small application that accepts an outreach goal, checks that the input is valid, creates a separate record for the request, and returns that record to the user.

For example, a user could submit:

> Find AI startups that may need our API observability product.

The application will return the same goal, empty collections for future results, and a status confirming that the application foundation is working.

Phase one establishes the path that later research, qualification, and email-writing steps will follow.

## What we will build

1. **Set up the Python project.**

   Create the application folders, a place for tests, and a file listing the required software packages.

   Use Python 3.12 or newer. FastAPI will handle incoming requests, Pydantic 2 will check the data, Uvicorn will run the application, and pytest will run the tests. HTTPX will support testing the API.

   The project should install into its own Python environment so its packages are separate from other projects on the computer.

2. **Create the entry point for an outreach request.**

   Provide an endpoint called `POST /outreach`. This is the address another application or a developer can use to submit a goal.

   Each request must contain one field, `goal`, holding the user's instructions as text.

   Remove spaces at the beginning and end while preserving the wording and capitalization. Accept goals between 1 and 2,000 characters after trimming.

   Reject missing goals, blank text, values that are not text, and unexpected fields. Invalid requests should receive the standard validation response with status `422`.

3. **Create a separate record for each request.**

   This record is called `OutreachState`. It holds the goal and the results collected as the workflow progresses.

   At the start, it contains the user's goal, empty lists of discovered and qualified prospects, empty collections for strategies, email drafts, and reviews, and a progress value of `"initialized"`.

   Each request must have its own collections. Adding information to one request must never change another request.

   These records live in application memory during the request. Saving them in a database belongs to a later phase.

4. **Add the workflow coordinator.**

   The workflow coordinator is the function that will eventually call the research, qualification, and writing components in order.

   For phase one, it receives the request's record, keeps its contents intact, changes the progress value to `"skeleton_ready"`, and returns the record.

   Keep this coordination in `workflow.py`. The API's responsibility is to receive the request and return the result.

5. **Connect the complete request path.**

   When a valid request arrives, the application checks the goal, creates a fresh record, passes it through the coordinator, and returns the result.

   A successful response has status `200` and contains these fields: `goal`, `prospects`, `qualified_prospects`, `strategies`, `drafts`, `reviews`, and `current_step`.

   The goal matches the accepted input, the result collections are empty, and `current_step` is `"skeleton_ready"`.

   The endpoint and its expected inputs and outputs also appear in the application's automatically generated API documentation.

6. **Write clear setup instructions.**

   Add a README explaining how to install the project, start it, submit an example goal, and run the tests.

   Explain that `"skeleton_ready"` means the request successfully passed through the application foundation.

   Finish by following the README from a fresh Python environment to confirm that the instructions work.

## Project structure

```text
app/
├── __init__.py
├── main.py
├── api/
│   ├── __init__.py
│   └── outreach.py
├── agents/
│   ├── __init__.py
│   └── researcher.py
├── prompts/
│   ├── __init__.py
│   └── researcher.py
├── orchestration/
│   ├── __init__.py
│   ├── graph.py
│   ├── nodes/
│   │   ├── __init__.py
│   │   └── research.py
│   ├── state.py
│   └── workflow.py
└── models/
    ├── __init__.py
    ├── client.py
    └── schemas.py

tests/
├── conftest.py
├── test_client.py
├── test_graph.py
├── test_researcher.py
├── test_research_node.py
├── test_schemas.py
├── test_state.py
├── test_workflow.py
└── test_outreach_api.py

pyproject.toml
AGENTS.md
.env.example
.gitignore
README.md
plan.md
FILE_GUIDE.md
```

## How we will check it

Automated tests verify that:

- A valid goal is accepted and returned correctly.
- Spaces at the beginning and end are removed.
- Missing, blank, incorrectly typed, and unexpected inputs are rejected.
- A 2,000-character goal is accepted; a 2,001-character goal is rejected.
- New records start with empty collections and the expected progress value.
- Changing one record leaves another record unchanged.
- The coordinator preserves the record's contents and updates its progress.
- Valid API requests reach the coordinator; invalid requests stop before it.
- The API returns the coordinator's result in the expected format.
- The endpoint's input and output formats are visible in the API documentation.

The tests run without external-service credentials or calls to external APIs.

A final manual check starts the application, submits an example goal through `POST /outreach`, confirms the response, and checks that the API documentation at `/docs` is available.

## Completion criteria and verification

- [x] A fresh environment can install and start the application using the README.
- [x] `POST /outreach` accepts a valid goal and returns the documented state.
- [x] Invalid requests produce validation errors before workflow execution.
- [x] Requests have independent state.
- [x] The workflow returns `"skeleton_ready"` with empty result collections.
- [x] All 44 automated tests pass without external API calls.
- [x] The application runs without external-service credentials.
- [x] The live API returns `200` for a valid goal and `422` for a blank goal; `/docs` returns `200`.

Verified in a fresh Python 3.12.9 environment. The dependency check found no conflicts. The temporary development server was stopped after verification.

## Boundaries and decisions

This plan uses the numbered **"Skeleton + State"** phase from the architecture. The larger research-and-qualification milestone spans phases 1–7.

The 2,000-character goal limit remains in place. Phase one introduced independent state collections and the `"skeleton_ready"` status; phase two added typed records. Phase four adds `"research_complete"` while retaining the earlier labels for existing records.

Qualification, search, memory, database storage, email writing, reviews, approvals, and Gmail integration remain in their later phases. The phase-four researcher is connected to LangGraph and uses phase three's shared model client. It reads supplied material; no search tool is implemented yet.

Redis, Celery, queues, vector databases, model routing, generic `BaseAgent` abstractions, and autonomous loops remain deferred. LangGraph checkpointing, interrupts, and subgraphs are also deferred to their specified later phases.

## Phase Two: Give workflow results a consistent format

**Status: implemented and verified.**

Each future workflow component needs a clear format for its results so the next component can use them reliably. Phase two adds five records:

| Record | Purpose |
|---|---|
| `Prospect` | Store researched company details, useful signals, potential decision-makers, and source references |
| `Qualification` | Keep a prospect's score, qualification decision, and reasons |
| `OutreachStrategy` | Describe the outreach angle and proposed next action |
| `EmailDraft` | Hold the email subject and body for a prospect |
| `ReviewResult` | Record the reviewer's decision, score, and issues |

The state now holds these records instead of loose dictionaries. It also includes `qualification_results` so scores and explanations remain available alongside the selected prospects. Strategies, drafts, and reviews remain organized by prospect ID.

Unknown website, industry, and decision-maker details can stay empty as `null`. Required text must contain more than whitespace, and unexpected fields are rejected. Each record gets its own result lists. Qualification scores must be whole numbers from 0–100, and decisions must be booleans. Review scores must be finite numbers; the architecture has not specified their scale. Email body formatting is preserved.

### Phase-two completion checks

- [x] All five records contain the fields specified in the architecture.
- [x] State collections use the new record types and independent defaults.
- [x] Qualification results are retained separately from qualified prospects.
- [x] Tests reject missing required fields, invalid text, invalid decisions, and invalid scores.
- [x] Populated records and state can be converted to JSON and restored without losing information.
- [x] API responses and documentation use the structured records, including `qualification_results`.
- [x] The full suite passes: 119 tests, without external API calls.

## Phase Three: Give agents one shared way to call a model

**Status: implemented and verified.**

The researcher, qualifier, strategist, writer, and reviewer will need different results, but they can all use the same model-call function. Phase three adds `app/models/client.py` so the provider's API details live in one place.

The shared `generate_structured` function receives task instructions, input text, an expected record class, and an injected client. It checks the arguments, asks the client for a response, validates that response against the chosen class, and returns the resulting record. A response can be a dictionary, JSON text, or an existing record; all go through validation.

`FakeModelClient` returns preset responses in order and records each call. This makes tests repeatable and lets them inspect the instructions sent by a future agent. Each fake gets its own response queue and call history.

`OpenAIModelClient` uses the async Responses API and requests structured output based on the record class. Real calls require an explicitly configured model and API key. Its context manager closes the SDK client it creates. An injected SDK client remains the responsibility of its caller.

Missing, incomplete, invalid, and refused outputs produce clear exceptions. Provider request errors also produce a shared client exception. The README explains these exceptions, includes a runnable fake example, and describes the optional settings in `.env.example`.

### Phase-three completion checks

- [x] Future agents have one asynchronous entry point for structured model calls.
- [x] The client can be injected or replaced with a mock.
- [x] A fake client returns deterministic responses without credentials or network access.
- [x] All five domain record types work with preset records, dictionaries, and JSON.
- [x] Invalid arguments stop before a client call; invalid outputs fail record validation.
- [x] Tests verify real SDK request formatting and response parsing using local simulated responses.
- [x] Tests cover refusals, missing or incomplete output, provider errors, and connection cleanup.
- [x] Dependencies install successfully and `python -m pip check` reports no conflicts.
- [x] The full suite passes: 166 tests, without external API calls.

Verified using Python 3.12.9 and OpenAI SDK 2.54.0. The suite reports one existing Starlette deprecation warning about its HTTPX-based API test client. No live model request was needed for verification.

## Phase 3.5: Introduce LangGraph behind the existing workflow interface

**Status: implemented and verified.**

Move the existing initialization step into LangGraph while preserving the phase-one-through-three interfaces and results. Keep `OutreachState`, the domain schemas, and the shared model client. The API continues calling `run_workflow(state)`.

### What changed

- Added `langgraph>=1.0,<2` to `pyproject.toml` using the existing dependency style.
- Created `app/orchestration/graph.py`. `build_graph` uses `StateGraph(OutreachState)` and compiles `START → initialize → END`.
- The initialize node returns only a partial update: `{"current_step": "skeleton_ready"}`. This preserves the existing status label and request/response contract.
- Updated `workflow.py` to await the compiled graph, validate its dictionary output using `OutreachState`, and copy all validated fields into the original record before returning it. It contains no execution-order decisions.
- Created `tests/test_graph.py` and expanded workflow and API tests without removing existing tests.
- Updated the file guide and README with the execution path, dependency installation, and plain-language explanations.

The graph is compiled once at module import. Each invocation receives separate request state. No checkpointing, interrupts, subgraphs, model routing, new agents, or external tools are configured. Future graph nodes will call application components for their business logic.

### Phase-3.5 completion checks

- [x] Ran the baseline suite before code changes: 166 tests passed.
- [x] LangGraph installs through the existing editable-install command.
- [x] The graph compiles with the existing Pydantic state and only the initialize node.
- [x] Graph invocation preserves the goal and populated result collections and updates progress.
- [x] Reusing the compiled graph keeps concurrent and subsequent requests separate.
- [x] `run_workflow` delegates through the graph and returns the original record with validated results.
- [x] Graph errors and invalid output propagate before the supplied record is updated.
- [x] The real API path reaches the graph, and invalid input stops before graph execution.
- [x] Focused graph, workflow, and API tests pass: 35 tests.
- [x] The full suite passes: 179 tests, including every original test, without live model or external-service calls.
- [x] `python -m pip check` reports no broken requirements.
- [x] A live server started without OpenAI credentials; valid and blank goals returned `200` and `422`, and `/docs` returned `200`. The temporary server was stopped.

Verified using Python 3.12.9 and LangGraph 1.2.13. Commands run:

```bash
python -m pytest  # Before implementation: 166 tests passed.
python -m pip install -e '.[dev]'
python -m pytest tests/test_graph.py tests/test_workflow.py tests/test_outreach_api.py
python -m pytest  # After implementation: 179 tests passed.
python -m pip check
```

The live check started Uvicorn on a temporary local port and checked the HTTP responses and API documentation. No new environment settings or external services were required.

### Sequence after phase 3.5

| Phase | Planned work |
|---|---|
| 4: Research agent | Implemented below: produce typed `Prospect` records from a goal and supplied material through a research node. |
| 5: Search tool | Add injectable search with typed results and source references. Tests use fake search results. |
| 6: Qualification | Produce existing `Qualification` records and select relevant prospects using a simple deterministic threshold. Connect qualification after research. |
| 7: Conditional routing | End when no prospects qualify; otherwise route to a temporary completion node. |

Later phases add structured goal interpretation, relationship memory, deterministic contact policy, strategy, writing, review, bounded revision, checkpointing, human approval, Gmail capabilities, and outcomes. Email sending requires a separate explicit instruction in its later phase.

Phase 3.5 ended with the initialization graph and empty results. Phase four, implemented next at the user's request, replaces that node with research.

## Phase Four: Research supplied material and return prospects

**Status: implemented and verified.**

Given a generic outreach goal and supplied evidence, produce typed `Prospect` records through the existing model client. LangGraph controls execution while the researcher component owns the research instructions and result checks.

### What changed

- Created `app/agents/researcher.py`, `app/prompts/researcher.py`, and `app/orchestration/nodes/research.py`, with their package files.
- Added `ResearchResult` in `schemas.py` as a batch wrapper containing the existing prospect records. No domain record or model-client abstraction was replaced.
- Added optional, strictly typed `research_material` text to `OutreachRequest` so HTTP callers can supply notes and source references before search exists. The goal-only request remains accepted; other unknown fields remain forbidden.
- Changed the graph to `START → research → END`, using the existing `OutreachState` and a per-invocation `ResearchContext` containing the researcher and material.
- Kept `run_workflow(state)` available and added optional keyword arguments for an injected researcher and material. It continues validating the graph result and returning the original state record.
- Added `research_complete` to the supported progress labels. The old labels remain accepted for earlier records.
- Added an injectable FastAPI client dependency. Nonblank material uses `OpenAIModelClient.from_env`; the dependency closes its client on success or failure. Empty material creates no client.
- Added HTTP `503` for missing model settings and `502` for model request, refusal, output, or evidence-check failures. Input errors continue returning `422` before client creation.
- Added `tests/test_researcher.py` and `tests/test_research_node.py`. Expanded graph, workflow, API, SDK, and shared-fixture tests, updating the deliberately changed node and status expectations.
- Updated `.env.example`, README, and the file guide with the research inputs, configuration, examples, and phase history. No new dependencies were required.

### Research behavior and boundaries

The researcher validates the goal and material, then makes one `generate_structured` call with the `ResearchResult` format. Its prompt supports different outreach goals, asks for supplied facts only, preserves references, leaves unknown optional details empty, and treats embedded material as evidence rather than instructions.

It rejects duplicate IDs, names absent from the supplied text, and missing or unsupported source references using the existing `ModelResponseError`. These are basic checks, not proof that each claim or relevance judgment is correct. No website is fetched or verified in this phase.

No material means no model call and an empty research result. The graph node preserves any existing prospects when no new material is supplied. With new material, the result replaces the prospect list, including an empty list when nothing matches. Other state collections are preserved.

The existing prospect schema still requires an organization name. Academic examples use a university or laboratory in `company_name` and the person in `decision_maker_name`. Broader schema evolution belongs to the later generic-goal phase.

Research does not assign final scores, qualify prospects, write drafts, or send messages. Search, memory, strategy, writing, review, approval, Gmail, checkpointing, interrupts, subgraphs, and model routing remain deferred.

### Phase-four completion checks

- [x] Ran the baseline full suite before modifying code: 179 tests passed.
- [x] Fake model responses produce typed prospects for job, academic, sales, and networking examples.
- [x] The researcher calls the existing structured-model function and preserves the goal and material in its input.
- [x] Empty material skips model access, and invalid input stops before a model call.
- [x] Invalid batch or prospect output, unsupported references or names, and duplicate IDs fail explicitly.
- [x] Existing model errors and refusals propagate through the component and node.
- [x] The research node returns partial updates without mutating its input state.
- [x] The real graph runs research and keeps concurrent request contexts separate.
- [x] The workflow returns the original state with typed results and preserves unrelated fields.
- [x] API requests can use dependency overrides with fake clients, and owned clients close after success or failure.
- [x] OpenAPI documents optional material and the new progress label.
- [x] The real OpenAI SDK parses a research batch using a local simulated transport.
- [x] Focused tests pass: 136 tests. The full suite passes: 233 tests, with no external-service calls.
- [x] `python -m pip check` reports no broken requirements.
- [x] A live Uvicorn server accepted a goal-only request with `200` and `research_complete`, rejected a blank goal with `422`, returned `503` for supplied material without model settings, and served `/docs` with `200`. The temporary server was stopped.
- [x] Both README fake-client examples run successfully; the complete graph example returns a typed academic prospect with its supplied source.

Commands run:

```bash
python -m pytest  # Baseline: 179 tests passed.
python -m pytest tests/test_researcher.py tests/test_research_node.py tests/test_graph.py tests/test_workflow.py tests/test_outreach_api.py tests/test_client.py
python -m pytest  # Final: 233 tests passed.
python -m pip check
```

The README's complete research workflow and earlier shared-client example were executed successfully with fake clients. Documentation links and code fences were checked. No live model call was used for verification.

The next phase is **phase five: an injectable search tool**. Implementation stops after phase four until the user requests the next phase.
