# Outreach Agent Plan

Phase one builds the application foundation. Phase two gives workflow results a consistent format. Phase three provides one shared way to request structured model output. Phase 3.5 introduces LangGraph as the internal workflow engine. Phase four adds research from supplied material. These phases are implemented; their work and verification are recorded below.

The complete-workflow code through phase 30 has now been added. This plan records its delivered scope and remains open to revision. External-service access still needs configuration, sending is disabled by default, and optional optimizations remain subject to measurements. The verification record distinguishes local checks from integrations not exercised live.

After the complete workflow, the user selected Groq. The existing model boundary now supports Groq alongside OpenAI. The README and file guide document its setup and distinguish the working API from proposed web, Telegram, and WhatsApp interfaces.

The user subsequently chose **CLI for V1**. It now runs the existing manager directly with terminal questions and saved-run review. SQLite is the local database; it needs no database account or key. Web, Telegram, and WhatsApp interfaces are deferred while we try real goals and configured integrations through the terminal.

## Product direction

The application supports goal-driven research and outreach informed by prior relationships. Goals can involve jobs, PhD opportunities, sales, networking, or partnerships. The user supplies a goal; the complete workflow researches relevant prospects and prepares grounded outreach for human review.

LangGraph owns execution order, state updates, and routing. Application components own business logic. The existing `generate_structured` model client owns model access. Replaceable tools handle external search and Gmail actions, and a database holds durable relationship information.

The original research-only graph remains available through `POST /outreach`. The complete graph runs through `POST /runs`, with saved-run inspection, approval decisions, event history, and separate reply processing.

## All phases at a glance

| Phase | What it adds | Status |
|---|---|---|
| 1 | Accept a goal, create a separate request record, and return it. | Complete |
| 2 | Define consistent records for prospects, decisions, strategies, drafts, and reviews. | Complete |
| 3 | Provide a shared model client with real and fake implementations. | Complete |
| 3.5 | Use LangGraph to coordinate the workflow. | Complete |
| 4 | Turn supplied research material into prospect records. | Complete |
| 5 | Search for evidence through a replaceable search tool. | Implemented; local checks |
| 6 | Assess prospects and select those relevant to the goal. | Implemented; local checks |
| 7 | Choose the next step based on qualification results. | Implemented; local checks |
| 8 | Turn different kinds of goals into a structured description. | Implemented; local checks |
| 9 | Store relationship information across requests. | Implemented; local checks |
| 10 | Retrieve useful past context for each qualified prospect. | Implemented; local checks |
| 11 | Apply clear rules about whether someone may be contacted. | Implemented; local checks |
| 12 | Decide why to contact the prospect and what to ask for. | Implemented; local checks |
| 13 | Write an email subject and body from the supplied context. | Implemented; local checks |
| 14 | Review drafts for accuracy, relevance, and tone. | Implemented; local checks |
| 15 | Revise rejected drafts within a fixed limit. | Implemented; local checks |
| 16 | Save workflow progress so an execution can resume. | Implemented; local checks |
| 17 | Pause for a person to approve, reject, or request an edit. | Implemented; local checks |
| 18 | Add API endpoints that resume a paused workflow. | Implemented; local checks |
| 19 | Read Gmail conversations for relevant relationship history. | Implemented; local checks |
| 20 | Create approved messages as Gmail drafts. | Implemented; local checks |
| 21 | Send approved messages with duplicate protection. | Implemented; sending disabled |
| 22 | Record outreach outcomes and update relationship memory. | Implemented; local checks |
| 23 | Understand replies and update the contact record. | Implemented; local checks |
| 24 | Record enough execution details to explain what happened. | Implemented; local checks |
| 25 | Measure the quality of each component and the full workflow. | Implemented; local checks |
| 26 | Choose models by task using measured results. | Optional router; real measurements pending |
| 27 | Add centralized limits, timeouts, and recovery controls. | Implemented; local checks |
| 28 | Process multiple prospects at the same time. | Implemented; sequential by default |
| 29 | Improve memory retrieval when simpler retrieval is insufficient. | Optional helpers; vector database deferred |
| 30 | Split a large workflow into smaller graphs. | Implemented; local checks |

Original phase records follow first. The scope added in phases 5–30 appears under [Remaining phases](#remaining-phases); that heading retains the earlier roadmap location. See [Complete workflow verification](#complete-workflow-verification) for the delivered result and its limits.

## Phase One: Build the application foundation

**Status: implemented and verified.** The following section records the original phase-one scope. Later completed phases extend this behavior, as described below.

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
├── main.py                  # API setup and resource cleanup
├── demo.py                  # Fictional local demonstration
├── settings.py              # Explicit settings and limits
├── observability.py         # Execution events
├── api/                     # Research, runs, decisions, contacts, replies
├── agents/                  # Goal interpretation, research, writing, review
├── qualification/           # Relevance scores and selection rules
├── strategy/                # Message approach before writing
├── prompts/                 # Model instructions for each component
├── models/                  # Records, shared clients, optional model routing
├── orchestration/
│   ├── graph.py             # Existing research-only graph
│   ├── workflow.py          # Existing run_workflow interface
│   ├── state.py             # Original request state
│   ├── full_graph.py        # Complete graph and subgraphs
│   ├── runs.py              # Start, inspect, resume, retry
│   ├── replies.py           # Separate incoming-reply graph
│   ├── checkpoints.py       # Execution persistence
│   ├── context.py           # Per-invocation services and bounded calls
│   ├── routing.py           # Decisions about the next step
│   └── nodes/               # Adapters between state and components
├── tools/                   # Search and Gmail adapters/fakes
├── memory/                  # Facts, retrieval, extraction, storage boundary
├── db/                      # Portable database tables and connection setup
└── security/                # Contact policy and operating limits

evals/                      # Reference cases, scoring, evaluation runner
tests/                      # Original tests plus complete-workflow checks
pyproject.toml
AGENTS.md
.env.example
.gitignore
README.md
plan.md
FILE_GUIDE.md
```

The individual files and inputs/outputs are explained in [FILE_GUIDE.md](FILE_GUIDE.md).

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

Phase four originally stopped at supplied-material research. The later implementation now adds search, qualification, relationship memory, database storage, strategy, writing, review, approval, Gmail adapters, and outcomes while retaining the original research path.

Redis, Celery, queues, a vector database, generic `BaseAgent` abstractions, and autonomous loops remain deferred. Checkpointing, interrupts, and subgraphs are implemented. An optional model router requires recorded measurements; production routes have not been selected.

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

Phase 3.5 ended with the initialization graph and empty results. Phase four, implemented next at the user's request, replaces that node with research.

Search, qualification, and conditional routing were subsequently implemented with the complete workflow. Their scope and the sequence through phase 30 are recorded in [Remaining phases](#remaining-phases).

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

The original next step was phase five. After the request to build all phases, the following scopes were delivered together and checked through the complete workflow.

## Remaining phases

### How we will use this roadmap

The original roadmap used one phase at a time. The request to implement all phases expanded this task across the remaining scopes, with baseline, focused, and complete-workflow checks. For later changes, finish the affected checks before moving on. After each phase, record what changed, what became possible, and how it was verified in this plan and [FILE_GUIDE.md](FILE_GUIDE.md). Update [README.md](README.md) whenever installation, configuration, startup, or usage changes.

For code changes, run the existing tests before changes where practical, add focused tests for the new behavior, and run the focused and full suites afterward. Use fake model, search, Gmail, and database responses in normal automated tests. Any tests that contact an external service must be clearly marked and run separately.

The sections below retain the scope of each phase. Actual file locations and responsibilities are recorded in the file guide. The existing project and research-only interfaces were preserved; the complete run API extends them. Keep business decisions in small application functions, graph ordering in LangGraph, model access in the existing shared client, and external actions behind replaceable tools. Supply fake tools and clients in tests rather than requiring credentials.

This is a working roadmap. If implementation shows that a step needs a different design, record the reason and update the affected future phases and the file guide together. Keep completed-phase history accurate. Current choices are Brave search, portable SQLAlchemy tables with local SQLite storage, optional PostgreSQL, a qualification threshold of 70, and centralized operating limits. Revisit these choices using measured behavior.

The complete request path is:

> Goal → interpretation → research → qualification → relevant memory → contact rules → strategy → writing → review → human approval → Gmail action → outcome and memory update.

Not every prospect will reach every step. Some will be rejected by qualification, blocked by contact rules, or declined by the user. Replies use a separate workflow. Sending code is present but disabled by default; enabling it and approving the current message are explicit requirements. Follow-up automation still requires a separate request.

## Phase Five: Add a search tool

**Status: implemented and locally checked.** Give the researcher a way to find evidence instead of depending only on notes supplied with the request.

- Add `app/tools/search.py` and a typed `SearchResult` record containing the useful result text and source reference. The search function receives a query and returns a list of results.
- Derive queries from the outreach goal. Keep the search provider's implementation inside the tool so the researcher can use either the real tool or a fake with the same behavior.
- Feed the results into research while retaining their source URLs. Keep supplied material usable as evidence too, and distinguish unsupported assumptions from facts.
- Keep the graph as `START → research → END`. Update the researcher, its request context, and setup instructions only where needed to connect search.

**Checks for this scope:** fake search results reach the researcher, goal-derived queries are passed to the tool, references survive in prospect records, and empty results or search failures have clear behavior. Normal tests make no live search requests.

**Completion criterion:** research can use an injected search tool and return prospects with traceable sources. Search-provider setup and the changed request behavior are explained in the README and file guide.

## Phase Six: Qualify prospects

**Status: implemented and locally checked.** Decide which discovered prospects are relevant enough to continue, and keep the reasons for that decision.

- Add `app/qualification/qualifier.py` and `app/orchestration/nodes/qualification.py`.
- Give the qualifier the original goal and one `Prospect`. Use a bounded structured model call through the existing client to return the existing `Qualification` record, including a score from 0 to 100 and reasons.
- Assess evidence, the person or organization's relevance, and whether further outreach work is worthwhile. Keep every decision in `qualification_results` and the selected prospects in `qualified_prospects`.
- Use a simple score threshold constant and explicit selection rules in code. Choose and document the initial threshold during implementation; add configuration only if it becomes necessary.
- Extend the graph to `START → research → qualification → END`.

**Checks for this scope:** fake model responses produce valid decisions; multiple prospects keep the correct decisions attached; scores at the threshold behave consistently; invalid output fails clearly; and state preserves both selected and rejected decisions.

**Completion criterion:** research results are assessed, qualification reasons are retained, and a repeatable rule selects the prospects that continue.

## Phase Seven: Route based on qualification

**Status: implemented and locally checked.** Let the workflow choose its next step based on whether any prospects qualify.

- Add `app/orchestration/routing.py` with a small function that reads qualification results and chooses the next graph step.
- End the workflow when there are no qualified prospects.
- When one or more qualify, continue to a temporary completion node. Later phases will replace that destination with useful outreach work.
- Keep this decision in code and connect it using LangGraph's conditional edges: connections that choose a destination from the current results.

**Checks for this scope:** cover no discovered prospects, discovered prospects with none qualified, one qualified prospect, and several qualified prospects. Verify the selected branch and preserved state.

**Completion criterion:** the graph follows the correct branch without adding memory or message writing yet.

## Phase Eight: Interpret different kinds of goals

**Status: implemented and locally checked.** Turn the user's sentence into a clear description that research and qualification can share.

- Add `OutreachGoal` in `app/models/workflow.py` alongside the complete-run records, while keeping the original schemas compatible. Include the original text, goal type, objective, target entity and description, desired outcome, constraints, and useful research signals.
- Add a goal-interpretation component and graph node. Keep the original goal available while passing the structured description to the researcher and qualifier.
- Support jobs, PhD opportunities, sales, networking, partnerships, recruiting, and investor outreach. Allow unfamiliar goal types rather than rejecting them because they are outside a fixed list.
- Review prospect fields where they assume a company so academic and other outreach goals have a clear representation. Preserve existing records where possible and document any required changes.
- Start the graph with `interpret_goal → research → qualification`.

**Checks for this scope:** include job/founder, professor/PhD, customer/sales, and networking examples, plus an unfamiliar goal. Verify that target, desired outcome, and constraints reach the downstream components without changing the user's original text.

**Completion criterion:** the same workflow understands different outreach purposes and downstream components use the shared interpretation.

## Phase Nine: Build relationship memory

**Status: implemented and locally checked.** Store useful information across requests so the application can remember earlier interactions.

- Add the needed files under `app/memory/`: `schemas.py` for memory records, `repository.py` for reading and writing them, `retrieval.py` for finding relevant records, and `extraction.py` for turning supplied interactions into structured facts.
- Add `app/db/database.py` and `app/db/models.py` when needed for database access and stored records. Start with a PostgreSQL-compatible design and document how to configure the actual storage.
- Support prior outreach, replies, known facts, preferences, objections, timing, referrals, opt-outs, and relationship context. Each extracted fact must retain its source so we can tell where it came from.
- Keep relationship memory separate from `OutreachState`. State belongs to one workflow execution; relationship memory can be useful across many executions. Saving workflow progress comes separately in phase 16.

**Checks for this scope:** records can be stored and retrieved through a fake or local test repository, sources are preserved, different contacts remain separate, and unsupported model assumptions are rejected as facts. Normal tests do not need live PostgreSQL.

**Completion criterion:** the application has a tested way to store and retrieve relationship information. Vector search is deferred until simpler retrieval proves insufficient.

## Phase Ten: Check relevant memory before outreach

**Status: implemented and locally checked.** Find what we already know about each qualified prospect before deciding how to contact them.

- Add a memory-check node after qualification and connect it to the memory retrieval functions.
- Retrieve prior contact, replies, opt-outs, requests to reconnect later, and other context relevant to this goal and prospect.
- Attach the relevant results to the prospect's workflow context, keeping their sources. Keep unrelated contacts and irrelevant history out of model inputs.
- Replace phase seven's temporary continuation with the memory check for qualified prospects.

**Checks for this scope:** new contacts return empty memory, known contacts return relevant history, unrelated records are excluded, and multiple prospects receive their own context. Check clear handling of retrieval failures.

**Completion criterion:** every qualified prospect reaches the next step with the relevant past context available.

## Phase Eleven: Apply contact rules

**Status: implemented and locally checked.** Make repeatable decisions about whether outreach to a prospect is allowed now.

- Add `app/security/contact_policy.py` with explicit rules and reasons for allowing, blocking, or deferring contact.
- Block opt-outs, missing or invalid recipient information, and duplicate outreach. Block or defer recently contacted people, and avoid starting fresh cold outreach during an active conversation.
- Base these decisions on code and available contact history. A model may help interpret context, but must not be the sole authority for these rules.
- Connect `memory_check → contact_policy`. End processing for blocked or deferred prospects; let allowed prospects continue toward strategy. Until strategy exists, use a temporary completion destination.

**Checks for this scope:** cover each rule, allowed contacts, mixed allowed and blocked groups, and repeated requests. Prove that blocked prospects cannot advance to later outreach steps.

**Completion criterion:** each prospect has a clear contact decision and reason, and the graph enforces that decision.

## Phase Twelve: Build an outreach strategy

**Status: implemented and locally checked.** Decide the purpose and approach of the message before writing it.

- Add `app/strategy/builder.py` and `app/orchestration/nodes/strategy.py`.
- Give the builder the structured goal, prospect research, and relevant memory. Return the existing `OutreachStrategy`, evolving its fields only if needed.
- Explain why this person or organization is relevant, why contact makes sense now, what evidence can personalize the message, what value or connection to offer, and what response to ask for.
- Support job, PhD, sales, and networking goals. Label hypotheses as hypotheses unless supplied evidence supports them as facts.
- Route only allowed prospects to strategy and store each result with the correct prospect.

**Checks for this scope:** fake model results produce strategies for different goals, proposed contact reasons use supplied context, hypotheses remain distinguishable, and blocked prospects never reach the builder.

**Completion criterion:** allowed prospects have a grounded message plan and a clear desired outcome.

## Phase Thirteen: Write email drafts

**Status: implemented and locally checked.** Turn the strategy into an email subject and body.

- Add `app/agents/writer.py`, `app/prompts/writer.py`, and `app/orchestration/nodes/writing.py`.
- Give the writer a `Prospect`, an `OutreachStrategy`, and relevant memory that is approved for use in the message. Return the existing `EmailDraft` through the shared model client.
- Ask for concise writing, supplied facts only, credible personalization, and a clear request aligned with the desired outcome.
- Keep the writer focused on writing. Research, qualification, and external email actions belong to their own components.
- Connect strategy to writing and store the draft against its prospect.

**Checks for this scope:** drafts contain a subject and body, receive the intended context, preserve prospect associations, and handle invalid model output. Use examples with missing personal details to check that instructions do not invite invented personalization.

**Completion criterion:** the workflow returns structured drafts based on the supplied evidence and strategy. Nothing is sent.

## Phase Fourteen: Review drafts

**Status: implemented and locally checked.** Check a draft before asking a person to approve it.

- Add `app/agents/reviewer.py`, `app/prompts/reviewer.py`, and `app/orchestration/nodes/review.py`.
- Give the reviewer the research, relevant memory, strategy, and draft. Return the existing `ReviewResult` with its decision and issues.
- Check unsupported claims, whether personalization has evidence, intrusive or inappropriate personalization, tone, length, the requested response, and contradictions with earlier relationship context.
- Connect writing to review and retain the review alongside the draft. Automated review is a quality check; human approval comes later.

**Checks for this scope:** valid review records are retained, malformed output fails clearly, and test examples cover supported drafts, invented claims, relationship contradictions, and inappropriate tone. Use fake responses to verify coordination; broader model-quality measurements come in phase 25.

**Completion criterion:** every draft has a review decision with useful reasons.

## Phase Fifteen: Add a bounded revision loop

**Status: implemented and locally checked.** Give rejected drafts a limited chance to improve using the review feedback.

- Route approved drafts to the next completion stage and rejected drafts back to the writer with the issues to address.
- Track the revision count in state. Start with a small documented hard limit, such as `MAX_REVISIONS = 1`.
- Review the revised draft again. When the limit is exhausted, stop with a clear manual-review outcome instead of looping indefinitely.
- Keep counters and routing in code, preserving the final draft and review for each prospect.

**Checks for this scope:** cover approval without revision, rejection followed by approval, repeated rejection, and multiple prospects with separate counts. Prove that the writer cannot exceed the revision limit.

**Completion criterion:** rejected drafts can be revised, and every path stops within the documented bound.

## Phase Sixteen: Save and resume workflow progress

**Status: implemented and locally checked.** Let an execution continue from its saved state instead of starting again.

- Add LangGraph checkpointing: saving the workflow's progress between invocations. Use an in-memory checkpointer for development and tests, and provide a PostgreSQL-backed path for durable use.
- Add identifiers for the conversation or execution thread and for individual runs. Keep different workflows' saved state separate.
- Update graph construction and workflow configuration to use the selected checkpointer, while preserving the application's entry point where possible.
- Keep checkpoints separate from phase nine's relationship memory. A checkpoint resumes an execution; relationship memory informs future executions.

**Checks for this scope:** save state, resume the same thread, preserve completed results, keep threads separate, and handle unknown identifiers clearly. Use deterministic local tests; verify durable storage separately when configured.

**Completion criterion:** an identified execution can resume with its saved progress, and database setup requirements are documented.

## Phase Seventeen: Pause for human approval

**Status: implemented and locally checked.** Give the user control over an automatically reviewed draft before any Gmail action.

- Add a LangGraph interrupt, a pause that waits for a person's decision, after automated review approves the draft.
- Show the prospect, research summary, relevant relationship memory, strategy, and email draft so the person has enough context to decide.
- Support approval, rejection, and a request to edit or revise. Approval continues toward the later Gmail stage; rejection ends processing; editing returns to the writing and review path within explicit limits.
- Keep the paused state in the existing checkpointed execution. Record which draft version the decision applies to.

**Checks for this scope:** the graph pauses before external email actions, exposes the expected decision context, and follows each decision correctly. A changed draft must receive approval for its current version.

**Completion criterion:** the graph can pause and resume around a human decision. Email sending is still absent.

## Phase Eighteen: Add approval and resume endpoints

**Status: implemented and locally checked.** Let an application or developer submit a decision for a paused workflow through the API.

- Add approval handling, likely in `app/api/approvals.py`, for approve, reject, and edit requests. Define strict request and response records.
- Use the existing run or thread identifier to locate the pause and resume that execution. Do not create a new outreach workflow for the decision.
- Return useful progress and results after resume, including another pause where applicable.
- Document the endpoint paths, decision payloads, identifiers, and errors in the README and automatic API documentation.

**Checks for this scope:** create a paused execution, submit each decision, and confirm the existing execution resumes. Reject invalid identifiers, malformed decisions, decisions for runs that are not awaiting approval, and stale draft versions.

**Completion criterion:** approval decisions can be submitted through documented endpoints and reliably resume the intended workflow.

## Phase Nineteen: Read Gmail conversations

**Status: implemented and locally checked.** Use actual conversation history as evidence for relationship memory.

- Add `app/tools/gmail.py` with operations to search threads and read a selected thread.
- Keep Gmail-specific authentication and API calls inside this tool. Make the tool replaceable with a fake for automated tests.
- Pass relevant conversation details to memory extraction and retrieval, retaining message or thread references as sources.
- Document the required Gmail configuration and read permissions when implementing this integration.

**Checks for this scope:** fake threads produce correctly associated conversation records, source identifiers are retained, unrelated threads are excluded, and access errors are handled clearly. Normal tests do not contact Gmail.

**Completion criterion:** relevant Gmail history can inform relationship context. This phase reads conversations only.

## Phase Twenty: Create approved Gmail drafts

**Status: implemented and locally checked.** Save the reviewed and human-approved message as a Gmail draft.

- Add `create_draft` to the Gmail tool and a graph step after human approval.
- Use the approved recipient, subject, and body. Keep rejected, unapproved, or subsequently changed messages out of this step.
- Store the returned draft, message, and thread identifiers where available, together with the draft version and creation result.
- Connect `approval → create Gmail draft → outcome`. Record the creation result now; phase 22 expands outcome storage and memory updates.

**Checks for this scope:** the fake Gmail tool receives the approved content, returned identifiers are retained, failures are clear, and unapproved or rejected drafts never reach creation. Confirm that no send operation is invoked.

**Completion criterion:** a human-approved message can become a Gmail draft without being sent.

## Phase Twenty-One: Add controlled email sending

**Status: guarded sending implemented; disabled by default.** The all-phase implementation includes this code, with explicit enablement and current human approval still required. No live email was sent.

- Extend the Gmail tool with a send operation and connect it only where sending is requested.
- Require human approval, an allowed contact-policy decision, a valid recipient, and the exact approved message version before sending.
- Prevent duplicate sends using a stable identifier and stored action status. This is called idempotency: repeating the same action request must not produce another email.
- Define how retries and uncertain provider responses are handled so retrying cannot accidentally send the message twice. Retain the returned message or thread identifiers.

**Checks for this scope:** a fake sender receives only eligible approved messages; opt-outs, invalid recipients, missing approvals, changed drafts, and duplicates are blocked. Simulated retries and uncertain responses must not produce duplicate sends.

**Completion criterion:** the explicitly requested sending path enforces all conditions and duplicate protection. Live sends require the intended recipient and message to be approved.

## Phase Twenty-Two: Record outcomes and update memory

**Status: implemented and locally checked.** Remember what happened after an outreach action or decision.

- Extend the memory and database records to store outcomes such as drafted, sent, replied, rejected, referred, reconnect later, no reply, and bounced.
- Connect relevant workflow events to outcome recording. Preserve the contact, execution, message identifiers, time, and source of the event.
- Extract useful facts from interactions into memory with their supporting source. Keep model guesses or unsupported interpretations from becoming established facts.
- Support draft-only operation when sending has not been enabled. A drafted message must never be recorded as sent.

**Checks for this scope:** each simulated event produces the correct outcome, sources remain attached, repeated events do not create duplicate records, and failed actions do not become successful outcomes.

**Completion criterion:** later requests can retrieve trustworthy outreach history and the facts supported by those interactions.

## Phase Twenty-Three: Process replies

**Status: implemented and locally checked.** Understand incoming responses and update what we know about the relationship.

- Add reply processing, using a separate inbound workflow if that keeps the initial outreach graph easier to understand.
- Load the relevant thread and classify the reply as positive, negative, referral, question, reconnect later, or unsubscribe/opt-out. Retain the original message and reference.
- Update outcomes, useful memory, and contact-policy information. An opt-out must prevent later outreach; a request to reconnect later must inform timing rules.
- Keep automated follow-up messages outside this phase unless they are explicitly requested separately.

**Checks for this scope:** sample replies cover each category, update the correct contact, retain their sources, handle repeated processing, and prevent opted-out contacts from advancing toward sending.

**Completion criterion:** replies improve relationship context and contact decisions without starting unrequested follow-up outreach.

## Phase Twenty-Four: Make execution explainable

**Status: implemented and locally checked.** Record enough detail to understand a workflow's behavior and diagnose failures.

- Add structured execution records for run and thread identifiers, node start and end, selected routes, model and tool calls, and their outcomes.
- Record elapsed time, token usage where available, failures, pauses, resumes, revision counts, and external actions such as Gmail draft creation or sending.
- Connect qualification reasons, contact-policy decisions, evidence, reviews, and approvals to the same execution so we can explain why a prospect reached an outreach action.
- Keep configuration and logging behavior documented. Avoid putting credentials or unnecessary private message contents into logs.

**Checks for this scope:** a simulated complete workflow and a failed workflow produce correctly associated records, including pause/resume and revision events. Confirm the record can explain the selected route and final outcome.

**Completion criterion:** we can answer “Why did this prospect receive this outreach?” from recorded evidence and decisions.

## Phase Twenty-Five: Measure quality

**Status: implemented and locally checked.** Evaluate whether the workflow produces useful, accurate results, beyond whether the code runs correctly.

- Add evaluation cases under `evals/`, covering different outreach goals and expected useful behavior. An evaluation measures output quality against an example or criterion.
- Check goal interpretation, prospect relevance and evidence, qualification decisions, memory relevance and freshness, strategy grounding, draft accuracy and tone, and the reviewer's ability to catch unsupported claims.
- Include complete-workflow checks for opt-outs, required approval, bounded revisions, and duplicate prevention. These code-enforced rules must remain passing tests, not subjective model judgments.
- Report component results separately so a weak step is identifiable. Clearly separate local deterministic checks from any optional live-model quality measurements and their costs.

**Checks for this scope:** the evaluation runner handles known good and bad examples, produces understandable results, and detects deliberate regressions. Normal tests remain independent of external credentials.

**Completion criterion:** we have repeatable quality measurements and a documented baseline for improving the workflow.

## Phase Twenty-Six: Choose models by task

**Status: optional router implemented and tested.** Production task routes remain unselected until real quality, cost, and response-time measurements justify them.

- Add `app/models/router.py` if measurements show a benefit from selecting different models for different tasks.
- Compare possible choices for interpretation, memory extraction, qualification, research, strategy, writing, and review. A cheaper model may suit a simpler task; a stronger model may be needed for more demanding work.
- Preserve `generate_structured` as the shared model-access boundary, validated output records, and fake clients for tests.
- Record why each choice was made and the quality level it must maintain. Keep the current model choice when there is no measured reason to change it.

**Checks for this scope:** configured tasks select the intended client or model, unknown tasks have clear behavior, and evaluations confirm that cost or speed improvements do not cause unacceptable quality loss.

**Completion criterion:** any model selection is justified by measurements and can be changed without rewriting business components. This phase can be deferred if one model remains adequate.

## Phase Twenty-Seven: Add production limits and recovery

**Status: implemented and locally checked.** Keep the workflow's time, cost, and external activity predictable under failures and larger workloads.

- Centralize testable limits for discovered and qualified prospects, search calls, revisions, graph steps, cost per run, and model and search timeouts.
- Preserve limits already introduced in earlier phases. Define what happens when each limit is reached and return a clear progress or error result.
- Add bounded retries, request-rate limits, and duplicate protection where required. Consider temporarily stopping calls to a repeatedly failing provider, called circuit breaking, and tested model fallbacks where useful.
- Never let retries bypass contact policy, approval, or duplicate-send protection. Keep limit values and service configuration in the setup documentation.

**Checks for this scope:** use simulated timeouts, repeated errors, exhausted budgets, and duplicate action attempts to prove that the limits hold and failures leave understandable state.

**Completion criterion:** the workflow stops or recovers predictably within its documented limits. Necessary limits belong in earlier phases too; this phase consolidates and expands them.

## Phase Twenty-Eight: Process prospects concurrently

**Status: bounded concurrent processing implemented and tested.** The default remains sequential; enable higher concurrency only after checking the individual flow and provider limits.

- Process several qualified prospects at the same time where measurements show a benefit, while preserving each prospect's contact rules, memory, strategy, draft, review, and approval.
- Keep each prospect's results, revision counts, and external action identifiers separate, then collect the results for the request.
- Set a concurrency limit so parallel work respects provider limits and the overall cost budget.
- Define how one prospect's failure is reported without mixing its results into another prospect's work.

**Checks for this scope:** overlapping fake operations keep records separate, respect the concurrency limit, preserve complete results, and handle one failed prospect while others finish. Policy, approval, and duplicate protections must still hold.

**Completion criterion:** concurrent execution improves throughput without changing the decisions or isolation of the reliable individual flow. Keep sequential processing if concurrency is unnecessary.

## Phase Twenty-Nine: Improve memory when needed

**Status: optional retrieval and consolidation helpers implemented.** External embeddings and a vector database remain deferred until retrieval measurements justify them; tests use fake vectors.

- Use measured retrieval problems to choose improvements. Options include searching by meaning, merging duplicate memories, tracking confidence and age, handling contradictions, and consolidating repeated information.
- Searching by meaning may use embeddings, numerical representations of text, and a vector database that searches those representations. Add this storage only if it solves a demonstrated problem.
- Keep supporting sources available, preserve opt-outs and contact rules, and distinguish older or disputed information from established current facts.
- Extend the existing memory boundary rather than replacing the workflow or adding unrelated abstractions.

**Checks for this scope:** compare retrieval on examples with related wording, duplicates, old facts, and conflicting information. Verify better relevance and continued enforcement of contact rules.

**Completion criterion:** a demonstrated memory problem is improved with measurable results. Defer this phase while simple retrieval is sufficient.

## Phase Thirty: Split complex workflows into subgraphs

**Status: research and outreach subgraphs implemented and checked.** The larger workflow now benefits from grouping these responsibilities; inbound replies also use a separate graph.

- A subgraph is a smaller workflow used inside a larger one. Extract cohesive sequences without changing their responsibilities or data contracts.
- Possible groups are research (`discover → search → synthesize → validate sources`), outreach (`memory → contact policy → strategy → write → review`), and reply handling (`load thread → classify → update memory → next action`).
- Preserve the existing model client, business components, approval requirements, checkpoint behavior, and external-action protections.
- Add separate checks for each smaller graph and keep full-workflow checks to prove they still connect correctly.

**Checks for this scope:** component graphs produce the expected records; the complete workflow keeps equivalent results, routes, bounded revisions, and pause/resume behavior.

**Completion criterion:** the graph structure is easier to follow without changing user-facing behavior. Defer this restructuring if the existing graph remains clear.

## Complete workflow verification

Verified on October 6, 2026. **All 319 automated tests pass**, including the original 233 tests and 86 added checks. The added checks cover the complete workflow, approval and editing, HTTP adapters, relationship memory, replies, durable checkpoints, evaluation scoring, failure isolation, and operating limits. Workflow tests use fake clients or locally supplied HTTP responses and require no external-service credentials.

We also created a fresh Python 3.12 environment and followed the README: installation with `python -m pip install -e '.[dev]'`, `python -m pip check`, the entire test suite, `python -m app.demo`, and the default evaluation command all succeeded. The demo paused at `awaiting_approval`, accepted its simulated approval, and recorded one fake Gmail draft. The four evaluation cases completed as simulations; their results do not measure a real model's quality.

Actual local Uvicorn servers passed these HTTP checks:

- The main application's `/docs` and `/openapi.json` returned `200` and described the new endpoints.
- A valid, trimmed goal sent to `/outreach` returned `200` and `research_complete`; a blank goal returned `422`.
- A complete run without model configuration returned `503` with its saved run identifier. Inspecting that failed run returned `200`.
- The separate demo application's `/runs` returned `201` and paused for approval. Submitting its current decision returned `200` and a `drafted` outcome. Its event endpoint returned `200`.

The optional PostgreSQL packages installed successfully and their driver/checkpointer imported. SQLite restart/resume was tested against real local files. No live PostgreSQL server, model provider, Brave account, or Gmail account was exercised. No real draft or email was created.

### Delivery decisions and limits

- Keep `POST /outreach` and `run_workflow(state)` compatible for existing research-only callers. Add `POST /runs` for the complete checkpointed path, using `WorkflowState` as an extension of the existing state.
- Preserve the shared model client and fake-client pattern. Model components validate prospect IDs; qualification uses a deterministic score threshold, and contact policy is code rather than a prompt decision.
- Use supplied addresses keyed by prospect ID or exact target display name. Missing addresses block outreach instead of being guessed. Preserve `company_name` for compatibility and add `entity_type` for person-only targets.
- Use local SQLite for runnable durable storage, while providing PostgreSQL-compatible tables and a separately installed PostgreSQL checkpointer. Relationship data and execution checkpoints stay distinct.
- Treat one revision as a hard shared allowance for rewrites and human edits. Changed drafts need review and fresh approval; decisions bind to the actual sender, recipient, subject, and body.
- Keep Gmail POST operations free of automatic retries. A persistent action claim and contact lock protect repeat/concurrent requests. An uncertain response requires manual inspection before another action.
- Leave sending disabled by default. This work used fake Gmail and made no live account changes or email sends.
- Keep real task-model selection and external semantic/vector retrieval subject to measurements. Implement optional routing/retrieval hooks and test them with local substitutes.
- Estimated cost reservations are adjustable estimates, not provider billing guarantees. Token usage is recorded when returned. The API serves one configured account; multi-account isolation and a shared multi-worker rate limiter would be separate deployment work.
- Live model, Brave, Gmail, and PostgreSQL integration checks require configured accounts/services. They are not claimed by the local verification.

### Groq provider follow-up

Extended phase three's shared model boundary with `GroqModelClient`, using the existing HTTPX dependency and record definitions. Complete runs, the original research endpoint, and explicitly requested live evaluations use the selected provider. `.env.example` selects Groq; existing installations without a provider setting retain the OpenAI default.

The full suite passes **343 tests**, including the previous 319 and 24 added provider checks. The added tests use locally supplied Groq responses and check request formatting, record validation, failures/refusals, connection cleanup, provider selection, saved failure inspection, approval without repeated model calls, and evaluation routing. Test settings and data are isolated from real account configuration. No live Groq call was made.

A custom web UI, Telegram bot, and WhatsApp adapter are possible interface work, separate from the numbered workflow phases. The later V1 decision below selects the CLI; the API and `/docs` remain available for development.

### V1 interface follow-up

Implemented `app/cli.py` as the V1 interface. Users enter goals and known recipient addresses, select supplied evidence or optional search, inspect results, approve/reject/edit drafts, view saved runs/events, and retry failed work. The initial run action choices are review-only (`none`) or Gmail draft creation. Draft approval is always an explicit terminal decision.

Added `app/orchestration/runtime.py` and shared it with the optional API. This opens the same SQLite relationship database and checkpoint files for both interfaces. Added bounded run summaries to the repository and cancellation recovery to the manager. Added the `outreach` command while retaining `python -m app.cli`.

V1 keeps database setup local: `.data/relationships.sqlite3` holds relationship, outcome, run, and event records; `.data/checkpoints.sqlite3` holds saved workflow progress. No database key is needed. Paused real runs can be resumed after reopening the CLI. Demo runs use temporary storage and fake clients. A configuration check reports setting presence and hides secrets; real provider acceptance requires an actual configured run.

Verification includes terminal input, no model calls on invalid requests, exact approval/rejection, edits and fresh approval, unsubmitted partial decision batches, local fake draft creation, events, configuration secrecy, interrupted-run recovery, and real SQLite restart/resume. **All 360 tests pass**, including the prior 343 and 17 new CLI checks.

Installation registered the `outreach` command. Actual terminal processes passed the interactive demo (start → pause → explicit approval → fake draft → events), normal startup with automatic creation of both SQLite files, a missing-key check returning the expected exit code, and `outreach --help`. No live provider request, real Gmail draft, or email send was made. README links, Markdown formatting checks, and file-guide coverage passed.
