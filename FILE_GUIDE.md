# File guide

This guide explains the working application in plain language. The [setup guide](docs/SETUP.md) explains how to run it. The [API guide](docs/API_GUIDE.md) describes requests used by the dashboard. Earlier work is preserved in [phase history](docs/PHASE_HISTORY.md) and the [previous file guide](docs/FILE_GUIDE_HISTORY.md).

## Follow one request

1. You talk normally to the Telegram bot. `ConversationService.queue()` saves your message, and a LangGraph conversation loop answers, reads files/public pages, searches when available, or proposes outreach. It remembers the last six exchanges across restarts. `/new` optionally resets this context; `/guided` opens the old step-by-step questions. Dashboard requests still enter outreach directly.
2. If you explicitly request email drafts, check the proposed request and press **Start outreach**. `AgentService.start()` validates its choices, saves a run and a job, and returns their identifiers immediately. A **run** holds results; a **job** is one queued piece of work. Uploaded-file jobs extract text locally before the run uses it. Ordinary conversation, research, and file questions do not create emails.
3. One worker takes the job. `RunManager` opens the saved **LangGraph workflow**, an ordered set of steps with explicit choices about where to go next.
4. The agent loads ready files, interprets the goal using relevant excerpts, researches uploaded/public evidence, qualifies prospects, resolves addresses, checks relationship history and contact rules, then writes and reviews messages.
5. Missing or ambiguous addresses pause the run for your selection. Requested Gmail drafts continue after automated review. App-only drafts and older paused approvals retain the shared approve/reject/edit controls.
6. The worker checks the connected account, recipient, exact message, contact policy, and action history. It saves each requested Gmail draft once and records the result. An uncertain write stays blocked for inspection.
7. The bot tells you when drafts are saved. You open Gmail, review/edit the actual drafts, and click **Send** yourself. The agent cannot send emails; the former sending flag cannot turn that on.
8. The dashboard displays the same saved run, sources, outcomes, events, and usage. No second research run is needed to switch interfaces.

For example, “Find professors studying AI observability” can get a research answer. “Prepare email drafts for these professors” proposes drafting. The default limit is five qualified prospects per run, so ten emails need smaller batches or a deliberate limit change. The included demo uses a fictional university and simulated services.

**State** means the information needed to continue work: your goal, evidence, drafts, current step, pending choices, and outcomes. It is saved in local SQLite by default or in one Supabase Postgres database when configured. Changing stores does not copy old records automatically; see [Supabase setup](docs/SUPABASE.md).

**Saved knowledge** is different from execution state. It holds passages from documents and website pages so you can find relevant information in a later conversation. Local embeddings represent each passage's meaning as numbers; pgvector compares them inside PostgreSQL. The new **Saved knowledge** dashboard view shows matches and source dates. **Connections → Storage validation** checks that records, checkpoints, originals, and retrieval work. Phase 45 below explains the added files and functions.

## Phase history: what changed when

Phases 1–30 built and refined the original foundation, structured records, research, full outreach workflow, memory, providers, evaluations, CLI, and documentation. Their detailed records remain in [the archive](docs/PHASE_HISTORY.md). Old paths in that archive describe that earlier version.

| Phase | What was built and which files changed | What became possible and how it was checked |
|---|---|---|
| **31 — Consolidate the core** | Moved orchestration into `app/agent`, shared records into `app/domain`, providers into `app/llm`, persistence into `app/storage`, and adapters into `app/connectors`. Removed the interactive CLI, research-only workflow, and obsolete entry points. | One outreach workflow remained. All 285 retained behavioral tests passed after the move. Tests for removed interfaces were retired. |
| **32 — Saved jobs and Telegram** | Added `services/application.py`, `storage/control.py`, the Telegram connector, cooperative cancellation, and shared decision storage. Updated graph events and run execution. | Guided conversations, duplicate-update handling, shared approval batches, live step reporting, retries, and queue controls work without blocking message handling. Tests cover unauthorized chats, stale buttons, restarts, editing, and cancellation. |
| **33 — Connected Gmail account** | Added `connectors/gmail/oauth.py` and owner authentication. Updated Gmail client, approval fingerprints, external actions, reply processing, and evaluation approval checks. | Google sign-in stores encrypted renewable credentials. Approved actions are tied to the connected account. Reply checks process up to five new messages and scan at most 20 tracked actions per request. Mocked OAuth/Gmail tests cover renewal, account changes, redaction, duplicates, and reply limits. |
| **34 — Browser research and recipient evidence** | Added `connectors/browser`, `domain/browser.py`, and `agent/nodes/recipients.py`; extended research and workflow records. | The agent can read public pages, retain evidence, collect explicitly published addresses, and ask about missing or ambiguous recipients. Tests check network restrictions, persistent page limits, source selection, and a real Chromium fixture with JavaScript and blocked requests. |
| **35 — Dashboard and local service** | Added `web/routes/control.py`, `web/static`, migrations, startup/shutdown, authentication, and instance locking. Replaced temporary API routes with `/api` jobs and shared controls. | The dashboard can inspect and approve a Telegram run. Automated tests cover login, CSRF, statistics, migrations, restart recovery, and an action finishing during cancellation. A real browser walkthrough exercised login → research → approval → simulated Gmail draft. |
| **36 — Packaging and handoff** | Updated README, this guide, setup/API instructions, `.env.example`, the diagram, and contributor instructions. Added Docker packaging and upstream browser sandbox notices. | A single service command starts local work. The [validation record](docs/VALIDATION.md) distinguishes completed checks from live account and container checks that still need the owner's environment. |
| **37 — File reading and research** | Added document records, a local extraction connector, durable file jobs, Telegram/dashboard uploads, and a migration. Updated interpretation, research, recipient checks, and setup. The detailed file-by-file explanation is below. | PDFs, images/scans, office files, and text can guide searches and become cited evidence. Real OCR, upload/restart handling, background separation, and file-driven search checks pass. |
| **38 — Gmail setup and website reading clarification** | Expanded `docs/SETUP.md`, clarified the credential warning in `.env.example`, and updated this guide. Prepared the ignored local `.env` for Gmail. | Google setup now has explicit project, consent, test-user, client, callback, and connection steps. Website reading from supplied URLs is explained separately from Brave discovery. The 58 targeted Gmail/browser/research checks pass; real Gmail consent is still pending. |
| **39 — Normal Telegram conversation** | Added `domain/conversation.py`, `agent/conversation.py`, `agent/prompts/conversation.py`, `services/conversation.py`, and `connectors/telegram/messages.py`. Updated Telegram handling, shared jobs, limits, demo behavior, tests, guides, and the diagram. Detailed explanations appear below. | Normal messages and file captions can receive answers, read evidence, and support follow-ups without `/new`. Outreach still enters the tested approval workflow. Eighteen new checks cover history, restarts, duplicates, read limits, cancellation, and safe handoff; the complete 376-test suite passes, including local Chromium/OCR. Live Telegram/model behavior remains an account check. |
| **40 — Model errors and budget explanations** | Updated model error handling, chat notifications, dashboard budget labels, tests, and setup documentation. | Known provider failures explain the cause without exposing secrets. Blocked models and rate limits stop without an automatic retry. Reserved budget is labeled separately from billing. The 391-test suite passes. |
| **After phase 40 — Prepare xAI configuration** | Added setup fields to `.env.example` and the ignored local `.env`; updated this guide. | This earlier change only reserved a place for the key and model choices. Phase 41 below connects those settings to the application. |
| **41 — Connect Grok on xAI** | Added `app/llm/xai_client.py` and its tests. Updated provider selection, safe errors, dashboard connection checks, test isolation, environment template, README, and setup/validation guides. | Telegram conversation and outreach can use Grok through the same saved workflow, budgets, and approvals. All 425 tests pass, covering the model-to-approval path, replies, duplicates, safe failures, and tokens. Live account acceptance still needs the owner's Telegram test. |
| **42 — Supabase state and requested Gmail drafts** | Added private Postgres configuration and restart checks; changed the email path to request-only drafts and manual Gmail sending. Updated Telegram, dashboard, tests, setup, and diagram. Detailed file explanations appear below. | State can use one hosted database. Requested drafts are saved once and announced; normal chat does not draft, and agent sending is blocked. Cloud connection still needs the owner’s project URL. |
| **43 — Model roles and tool calls** | Added separate instruction, reasoning, and research model choices; connected validated native tool calls to the conversation workflow. | Model requests use the configured role. Unsupported tools and invalid arguments are rejected before execution. Detailed files and checks appear below. |
| **44 — Stop and continue** | Saved conversation progress, completed tool results, and task links in the existing database and LangGraph checkpoints. | Saying **continue** resumes stopped work with the same goal, evidence, and usage counters. Restart tests check that completed reads are reused. |
| **45 — Private originals and saved knowledge** | Added Supabase file storage, local embeddings, pgvector retrieval, provisioning, and dashboard search/storage checks. Detailed file explanations appear below. | Earlier files and website passages can be searched across conversations. The 494-test suite and a real browser walkthrough pass; hosted setup still needs the owner's credentials. |

## Application entry and configuration

| File | Purpose, main inputs, and outputs |
|---|---|
| `app/main.py` | `main()` explicitly loads the project’s `.env`, reads startup options, and starts Uvicorn, the web server. `create_app()` assembles routes, authentication, the job worker, and Telegram tasks. Startup applies migrations and recovers interrupted jobs; shutdown lets bounded external actions record results. `/health` reports whether background tasks are still alive. |
| `app/settings.py` | `Settings.from_env()` converts environment values into checked settings. It accepts `xai`, `groq`, or `openai` and defines database, owner, connector, and operating-limit configuration. The template selects xAI; an absent provider setting retains Groq for older installations. It does not contact providers. Secret fields are omitted from the settings object's printed representation. |
| `app/demo.py` | `build_demo_manager()` supplies fake model, search, browser, and Gmail clients to the real workflow. `DemoModelClient` produces fictional records by the requested record type, including a clearly labeled simulated chat reply. `demo_request()` provides a sample request for tests. Start the demo with `python -m app.main --demo`. |
| `pyproject.toml` | Lists Python requirements, dependencies, optional test/Postgres packages, the `outreach-server` command, packaged dashboard assets, migrations, and pytest settings. |
| `.env.example` | Documents configuration names without real secrets. Selects `OUTREACH_MODEL_PROVIDER=xai`, `XAI_MODEL=grok-4.3`, and `XAI_REASONING_EFFORT=none`, with a blank `XAI_API_KEY`. Alternative provider settings are explained in `docs/SETUP.md`. |
| `.env` (local only) | Stores your real keys and local settings. Service startup loads it automatically. Keep each setting once, because a later empty assignment can override a saved key. Phase 41 preserves the entered xAI key, removes its empty duplicate, and explicitly selects xAI. Other settings stay intact; this file stays outside Git. |
| `.gitignore` | Keeps credentials, databases, environments, and build outputs out of Git. After phase 39, the root `AGENTS.md` and `plan.md` were also made local-only: their files remain on this computer, but Git no longer tracks future changes to them. |
| `AGENTS.md` (local only) | Instructions for coding assistants working in this checkout, including documentation and verification expectations. It is ignored by Git and is not included in fresh clones. |

Every `__init__.py` marks its directory as an importable Python package. These files do not start the service or call external providers.

## Agent core

A **node** is a small workflow step. It receives the current state and the run’s services, then returns a dictionary containing only the fields it changed. LangGraph combines those changes with the saved state.

| File | Purpose and main functions |
|---|---|
| `app/agent/graph.py` | `build_full_graph(checkpointer)` returns the main executable workflow. `build_research_graph()` groups interpretation, research, and qualification; `build_outreach_graph()` groups strategy, writing, and review. `observed()` wraps steps with cancellation checks, timings, events, and current-step reporting. |
| `app/agent/state.py` | Defines `OutreachState`: the goal and separate collections for prospects, qualifications, strategies, drafts, reviews, and progress. The complete state extends it in `domain/workflow.py`. New runs never share mutable collections. |
| `app/agent/context.py` | `WorkflowContext` passes services to nodes. `ManagedModelClient` and `ManagedSearchTool` reserve persistent budgets before calls, enforce timeouts, and record usage. Model failures record safe HTTP status/reason details. Known key, permission, and rate-limit failures stop without an automatic second attempt. |
| `app/agent/routing.py` | `after_qualification`, `after_contact_policy`, `after_review`, and approval routing functions return the next step’s name. They stop unsuitable outreach and bound revision loops. |
| `app/agent/policy.py` | `check_contact()` takes a recipient and saved relationship facts and returns whether contact is allowed, with reasons. `message_fingerprint()` makes a hash identifying the sender, recipient, message, intended action, and Gmail account. A changed message or account no longer matches its old approval. |
| `app/agent/replies.py` | `process_reply()` takes one known inbound message, prevents repeat processing, classifies it, extracts supported facts, and updates contact rules. `build_reply_graph()` organizes this small inbound workflow. An explicit opt-out is stored before optional model work. It never sends an automatic reply. |

### Workflow nodes

| File under `app/agent/nodes/` | What it does with the state |
|---|---|
| `goal.py` | `goal_node()` turns the raw goal into a structured description of whom to find and why. |
| `discovery.py` | `discovery_node()` combines notes, optional search, and browser evidence, then returns sourced prospects and visited-page records. |
| `qualification.py` | `qualification_node()` scores each prospect against the goal and keeps a bounded list of qualified prospects. |
| `recipients.py` | `prepare_recipients()` prefers user-supplied addresses, otherwise checks addresses published on cited pages. One candidate can be selected automatically; zero or multiple candidates pause the run. `validate_selections()` requires an address or skip for every pending prospect. `choose_recipients()` resumes with those choices and retains the original evidence. |
| `memory.py` | `memory_node()` retrieves saved relationship information and, when enabled, relevant Gmail conversations for each contact. |
| `contact.py` | `contact_node()` applies opt-out, recent-contact, conversation, and timing rules before writing. |
| `strategy.py` | `strategy_node()` creates a grounded approach for each allowed prospect. |
| `writing.py` | `writing_node()` drafts or revises a message using the goal, sender background, strategy, and evidence. |
| `review.py` | `review_node()` checks drafts and records review results. A failing draft can be revised within the shared revision limit. |
| `approval.py` | `prepare_approval()` skips the in-app approval pause for explicitly requested Gmail drafts. App-only drafts still get exact-message cards. `human_approval()` applies a complete decision batch, and `validate_decisions()` rejects stale choices. This also preserves older pending approvals. |
| `external.py` | `external_node()` accepts reviewed state, checks account identity, contact policy, and saved action history, and returns confirmed draft outcomes. It rejects sends. App-only completion still requires approval. `finish_node()` saves outcomes and interaction history. An uncertain write is recorded without repeating it. |
| `common.py` | `for_each()` limits concurrent prospect work and records individual failures. `allowed_prospects()` filters eligible targets. `failure()` creates a consistent failed outcome. Cancellation propagates instead of becoming an ordinary prospect failure. |

### Components and prompts

Components perform one task without deciding the overall workflow order. Their inputs are checked domain records; model responses must fit the requested result format.

| File under `app/agent/components/` | Purpose |
|---|---|
| `goal_interpreter.py` | `interpret_goal()` converts a natural-language goal into `OutreachGoal`. |
| `researcher.py` | Collects permitted notes/search/browser evidence and asks the model for prospects. Enforces source grounding and prospect limits. Browser reading stays within the saved page budget and follows links only one level deep. |
| `qualifier.py` | `qualify()` takes a goal and prospect and produces a qualification score, decision, and reasons. |
| `strategy.py` | `build_strategy()` takes prospect, goal, sender background, and memory; returns a strategy supported by that information. |
| `writer.py` | `write_draft()` takes strategy and supporting information; returns an `EmailDraft`. Revision inputs include review feedback. |
| `reviewer.py` | `review_draft()` takes a draft and its evidence; returns a review score, approval flag, and issues. This is automated review, separate from your final approval. |
| `memory/extraction.py` | Extracts facts only when their quoted evidence appears in the supplied conversation. Recognizes explicit opt-outs without needing a model. |
| `memory/retrieval.py` | `candidates()` loads unexpired facts; `retrieve()` ranks them for the goal and returns a bounded selection. Gmail history is read by the memory node using the Gmail connector. |
| `memory/advanced.py` | `consolidate()` groups matching facts, `possible_conflicts()` flags disagreements, and `semantic_retrieve()` optionally ranks facts by similarity vectors. They are not a separate production database requirement. |

The files `prompts/goal.py`, `researcher.py`, `qualification.py`, `strategy.py`, `writer.py`, and `reviewer.py` contain model instructions for their matching components. They explain allowed evidence and required output; Python still controls approval, routing, budgets, and external actions. Website text is evidence, not application instructions.

## Shared data and model providers

| File | Purpose, inputs, and outputs |
|---|---|
| `app/domain/schemas.py` | Pydantic records for a basic goal request, prospects, qualifications, strategies, drafts, and reviews. Pydantic checks types and required fields before the data moves on. |
| `app/domain/workflow.py` | Adds `WorkflowRequest`, `WorkflowState`, sender/recipient records, approval requests/decisions, reply records, outcomes, and memory facts. A request includes research choices and Gmail action; a state adds results, account identity, versions, and progress. Goals remain trimmed and limited to 2,000 characters. |
| `app/domain/browser.py` | `PageEvidence` stores a page URL, title, retrieval time, bounded text, links, explicitly found email addresses, and any read error. |
| `app/llm/client.py` | Defines the common structured-model interface, validation/error helpers, OpenAI adapter, and `FakeModelClient`. `generate_structured()` returns a validated record. `ModelProviderError` takes a provider, known reason, and optional HTTP status; its `public_message` returns an application-written explanation safe to show the owner. |
| `app/llm/groq_client.py` | Sends structured requests to Groq, checks returned JSON, and captures reported token usage. `_request_failure()` translates an HTTP response into a safe failure reason, including organization/project model blocks. Raw provider messages and unknown error codes are not saved or displayed. |
| `app/llm/xai_client.py` | `XAIModelClient.from_env()` reads the xAI key, model, and reasoning choice. `generate_structured()` takes instructions, input text, and a Pydantic record type; makes one xAI Responses request; then returns a locally checked record, such as a qualification score. It bounds visible output, requests `store=false`, and captures token counts. Incomplete output, refusals, or invalid records stop the call. `_request_failure()` returns fixed error text without copying private provider content. `aclose()` closes the connection it owns. |
| `app/llm/router.py` | Retains optional measured model-routing helpers. The normal service uses the single configured provider; it does not automatically choose a cheaper model. |

## Connectors

A **connector** is an adapter between our application and an external service. Fake adapters implement the same operations using local examples, which lets tests exercise real workflow logic without keys or network calls.

| File | Purpose and main operations |
|---|---|
| `app/connectors/search.py` | `BraveSearchTool.search()` takes a query and returns titles, URLs, and snippets. `FakeSearchTool` returns preset examples. Brave finds pages; the browser reads page contents. Supplied URLs or notes can avoid Brave entirely. |
| `app/connectors/telegram/client.py` | `TelegramClient.call()` sends Bot API requests, bounds timeouts, and sanitizes errors. `RateLimited` carries a retry delay. `FakeTelegram` records calls without contacting Telegram. |
| `app/connectors/telegram/bot.py` | `TelegramBot` sends ordinary text/file captions to the saved conversation queue. `/guided` retains the optional form. It creates review/recipient controls and translates commands into shared-service calls. `poll()` saves owner-only private updates before advancing Telegram’s offset. `process_one()` handles saved updates. `deliver_one()` sends durable outbox messages and avoids blindly repeating an uncertain delivery. Buttons reference saved current versions. |
| `app/connectors/gmail/client.py` | `GmailClient` searches/reads threads and creates drafts or sends messages. `encode_message()` creates the email payload with checked headers. `contact_messages()` extracts plain-text messages involving an exact address. `FakeGmailClient` records simulated operations. |
| `app/connectors/gmail/oauth.py` | `GmailAccount.connect_url()` starts Google sign-in; `complete()` verifies the owner session and granted permissions, then saves the verified address and encrypted tokens. `CredentialVault` encrypts/decrypts secret records. `token()` renews an expired token. `disconnect()` removes local credentials and attempts Google revocation. `BoundGmail` holds the account lock through each request so an approval cannot switch accounts mid-action. |
| `app/connectors/browser/client.py` | `BrowserClient.read(url)` returns `PageEvidence` using a fresh sandboxed Chromium session. `extract_emails()` accepts addresses actually present in visible text or a single-recipient contact link. `FakeBrowser` returns local evidence. Browser sessions have no personal login cookies, and submissions/downloads/WebSockets are blocked. |
| `app/connectors/browser/network.py` | `parse_public_url()` checks HTTP/HTTPS URLs and ports. `public_address()` rejects private, local, reserved, or mixed public/private DNS answers. `PublicProxy` connects to the validated IP, covering redirects and subrequests too. This prevents a second DNS lookup from changing the destination to a private service. |
| `app/connectors/browser/managed.py` | `ManagedBrowser.read()` reserves a page attempt in the database before browsing, saves evidence, and reuses saved evidence on retries. Restarts do not reset limits. |

## Services and persistence

| File | Purpose and main operations |
|---|---|
| `app/services/application.py` | `AgentService` is the shared entry point for both interfaces. `start()` queues outreach; `stage_decision()` saves one choice; `submit_choices()` queues a complete batch; `select_recipients()`, `retry()`, and `cancel()` control saved work. `execute_one()` also runs chat jobs through `ConversationService`. Chat retries stay in the conversation graph. `check_replies()` processes bounded new inbound messages. `overview()`, `list_runs()`, and `details()` return dashboard data and paginated events. |
| `app/services/runs.py` | `RunManager` connects saved runs to LangGraph. `execute_new()`, `resume()`, `select_recipients()`, and `retry()` execute or continue a saved run. `_execute()` owns leases, checkpoints, failures, and cancellation. `context()` supplies per-run adapters, including an account-bound Gmail client. `real_model_client(settings)` opens only the selected xAI, Groq, or OpenAI adapter on the first model call and closes it afterward. Approval without new model work does not open a connection. |
| `app/services/runtime.py` | `open_runtime()` opens the database, checkpoint connection, HTTP clients, and configured connectors, then closes them together. Demo mode injects fake services. |
| `app/services/auth.py` | `OwnerAuth.login()` verifies the configured password and creates an opaque session. Password verification uses Argon2 hashing. `require_owner()` checks either an API key or owner session; browser writes also need a CSRF token, which prevents another site from silently submitting owner actions. Browser sessions expire on restart; saved approvals remain. |
| `app/services/cancellation.py` | `check_cancelled()` reads the saved stop request and raises `RunCancelled` at a safe boundary. A Gmail action already underway finishes recording its result. |
| `app/services/instance.py` | `instance_lock()` locks the data directory while the service runs. A second local process using that directory fails clearly instead of starting a second worker/poller. |
| `app/services/limits.py` | `Limits` defines page/call counts, timeouts, concurrency, contact windows, revision limits, and estimated spending. Ordinary chat has a smaller default allowance: six model attempts and five tool selections per message, also constrained by the overall limits. Estimated cost is a configured per-call reservation, not a provider invoice. |
| `app/storage/models.py` | Defines tables for contacts, memory, interactions, runs, traces, action locks, and the external-action ledger. A ledger is the durable record used to recognize an already attempted action. |
| `app/storage/control.py` | Defines job, run-metadata, key/value, Telegram inbox, and outbox tables. `ControlStore.enqueue()` saves a run and initial job together, labeling chat separately from outreach and recording its latest turn in the same transaction. `claim()` honors queue pause. `recover()` marks interrupted work. Other methods persist conversations, approval selections, update offsets, page counts, and encrypted connector records. A repeated request key returns its original job. |
| `app/storage/database.py` | `create_database(url, private_schema=False)` opens SQLite or Postgres and applies existing migrations. Supabase uses the private `outreach` schema and a small connection pool. Failures close the connection instead of switching stores. |
| `app/storage/repository.py` | Reads/writes relationship facts, outcomes, runs, budgets, leases, and action claims. It is reused by the workflow, reply processing, and shared service. |
| `app/storage/checkpoints.py` | `open_checkpointer(settings)` opens LangGraph’s progress store. SQLite is the default; a Supabase URL selects Postgres in the same `outreach` schema as app records. Its serializer recognizes current and earlier domain record names. |
| `app/storage/events.py` | `trace()` writes timestamped events and updates the currently running node. `events()` returns a run’s ordered trace. Events record useful metadata, not credentials or full model prompts. |
| `migrations/env.py` | Connects Alembic, the migration runner, to the application’s existing database connection. |
| `migrations/versions/v001_connected_service.py` | The first versioned migration adopts earlier tables without discarding data, adds service tables, and backfills metadata for existing runs. It deliberately has no destructive automatic downgrade. |

With no Supabase URL, the local installation uses **SQLite**, with two files: `relationships.sqlite3` stores application records and `checkpoints.sqlite3` stores LangGraph progress. A configured Supabase URL instead puts both kinds of state in one hosted Postgres database; local records are preserved but not copied. SQLite files live under `OUTREACH_DATA_DIR`; the demo uses its `demo/` subdirectory. Credentials are encrypted in the application database; their encryption key stays in your environment.

## Dashboard and deployment files

| File | Purpose |
|---|---|
| `app/web/routes/control.py` | Authenticated `/api` routes validate incoming data and call `AgentService`. Run/reply/resume work returns HTTP 202 with a job identifier. Connector routes handle Google sign-in and status. `connections(request)` returns connector status, including whether the selected model provider's key is present, without returning credentials. The demo-only Telegram endpoint exercises the bot adapter locally. |
| `app/web/static/index.html` | The dashboard’s page structure: login, navigation, content area, and run/edit forms. |
| `app/web/static/app.js` | Fetches shared-service data, renders views, stages decisions, and submits controls. The new-run form accepts known addresses; run details retain completed drafts, reviews, decisions, and source retrieval times. Refreshes the visible view every five seconds while leaving active form entry alone. `node()` creates text safely instead of interpreting external content as HTML. Run submission preserves a request key after a lost response. |
| `app/web/static/app.css` | Styles the responsive dashboard, review cards, forms, tables, status badges, and compact logs. |
| `Dockerfile` | Builds the service with Postgres packages, Chromium dependencies, and local OCR, then runs it as a non-root user. |
| `compose.yaml` | Starts one container with persistent data, local port binding, health checks, graceful shutdown, and browser sandbox configuration. |
| `.dockerignore` | Excludes local credentials, databases, Git history, and environments from the build context. |
| `docker/seccomp_profile.json` | Upstream Playwright system-call profile allowing Chromium’s sandbox to create user namespaces. |
| `docker/PLAYWRIGHT_LICENSE`, `THIRD_PARTY_NOTICES.md` | Preserve the upstream profile’s Apache 2.0 license and attribution. Our project remains MIT licensed. |
| `README.md` | Short project introduction, working features, diagram, and demo command. |
| `docs/SETUP.md` | Local configuration, Telegram/Google setup, daily operations, and Docker instructions. |
| `docs/API_GUIDE.md` | Current authenticated endpoints and request/response examples. |
| `docs/VALIDATION.md` | Records what was actually tested and the remaining live-environment checks. |
| `docs/assets/workflow.mmd`, `workflow.svg` | Editable Mermaid flowchart and its rendered image. Shows ordinary chat, explicit draft requests, saved state, and final review/sending by the owner in Gmail. |
| `plan.md` (local only) | The working direction, defaults, and acceptance criteria for this checkout. It is ignored by Git; the shared README, setup guide, phase history, and validation record document the published project. |
| `CONTRIBUTING.md`, `LICENSE` | Contributor workflow and MIT licensing terms. Contributors retain their copyright and license contributions under MIT. |

## Tests and evaluations

The validation record lists completed automated suites, including optional Chromium and real image/scanned-PDF OCR fixtures. All four simulated evaluation scenarios pass. Packaging and restart checks are recorded in [validation](docs/VALIDATION.md).

**Tests** check behavior with known inputs. **Evaluations** score outreach results against small reference cases. A successful simulation confirms the workflow and scoring logic; it does not prove a real model’s research accuracy or writing quality.

| File | What it checks in everyday language |
|---|---|
| `tests/conftest.py` | Provides fresh fictional records and isolated databases/settings. Removes exported xAI, Groq, OpenAI, and application settings during each test so local credentials cannot accidentally turn tests into live calls. |
| `tests/test_schemas.py`, `test_state.py` | Input types, goal trimming/length, strict records, JSON conversion, and independent run collections. |
| `tests/test_client.py`, `test_groq_client.py` | Structured response validation, safe provider failure explanations, malformed error bodies, token information, and Groq configuration. |
| `tests/test_xai_client.py` | Uses simulated HTTP responses to check xAI request bounds, JSON validation, token counts, key selection, and safe errors. Runs a Telegram greeting and a six-call outreach workflow through the real adapter; checks duplicate messages, approval without extra calls, dashboard key status, and bounded retries. No paid model requests are made. |
| `tests/test_researcher.py` | Research limits, accepted evidence, grounded URLs, duplicate prospects, and malformed model output. |
| `tests/test_full_workflow.py` | Goal-to-draft behavior, qualification, review loops, edit/reject/approve decisions, account/action fingerprints, and duplicate external-action protections. |
| `tests/test_memory_policy.py` | Supported memory quotes, relevance/expiry, opt-outs, contact timing, and reply handling. |
| `tests/test_checkpoints_controls.py` | Saved progress, resume/retry behavior, call budgets, leases, and bounded execution. |
| `tests/test_tools.py` | Search/Gmail adapters, correct email payloads, plain-text conversation parsing, and external failures. |
| `tests/test_service.py` | Immediate job acknowledgments, replay protection, queue pause, complete multi-prospect choice batches, cancellation, current-step reporting, reply limits, statistics, and restart-preserved approvals. |
| `tests/test_telegram.py` | Owner-only private access, repeated updates, restart-preserved conversation progress, guided fake-service outreach, cross-interface approvals, stale decisions, safe message chunking, and rate limits. |
| `tests/test_gmail_oauth.py` | Encrypted tokens, refresh, revoked access, session-bound sign-in, verified account identity, changed-account blocking, and disconnect cleanup. |
| `tests/test_browser.py` | Public network boundaries, explicit email extraction, persistent page budgets, recipient ambiguity, and user-address precedence. |
| `tests/test_browser_integration.py` | An optional real Chromium test uses a local fixture to verify JavaScript-rendered text, blocked submissions, and blocked private redirects. It needs Chromium installed, but no public network or credentials. |
| `tests/test_full_api.py` | HTTP 202 job behavior, input rejection, authentication, CSRF, rate limits, redacted errors, and shared run controls. Old `/outreach` and `/runs` entry points return 404. |
| `tests/test_server_recovery.py` | Single-instance locking, data-preserving migrations, retry after interrupted job claim, and recording a Gmail action that finishes during cancellation. |
| `tests/test_evaluations.py` | Four fictional scenarios score correctly; missing outputs, unsupported claims, wrong sources, and broken revision limits are detected. |
| `evals/cases.json` | Four reference scenarios: jobs, academic outreach, sales, and networking. |
| `evals/run.py` | `evaluate()` runs each scenario in an isolated workflow and returns scores, duration, calls, and estimated cost. The default uses scripted responses. `--live` explicitly uses an exported model configuration and consumes provider credits; it does not perform Gmail actions. |
| `evals/scoring.py` | `score_run(state, reference)` compares targets, sources, qualification, memory, writing, and reviews. Saved drafts must match their account/content fingerprint and contact checks; agent sends fail the workflow rule. Missing supporting records also fail instead of crashing the evaluation. |

Use `python -m pytest` for ordinary offline checks, `RUN_BROWSER_TESTS=1 python -m pytest` to include Chromium, and `python -m evals.run` for the four simulated evaluations. Real Telegram delivery, Google consent, and live Gmail writes are recorded separately in the validation guide.

## Phase 37 — Read files and use them in research

You can now attach files in a Telegram goal conversation or the dashboard's **New run** form. The shared worker extracts text locally, stores it, and passes cited evidence into the existing LangGraph workflow. A file marked **background** describes you; a file marked **research** describes the material you want the agent to investigate. The goal interpreter uses relevant topics and skills to guide the existing search. Drafting, human approval, contact rules, and sending controls still apply.

**OCR** means optical character recognition: turning printed text in an image into editable text. This implementation uses Tesseract locally for images and PDF pages without selectable text. It does not perform general visual reasoning about photographs or charts. Extraction does not require another model key; starting an outreach run can send extracted text to your configured model and use its normal call budget.

| New or changed file | Purpose, inputs, and outputs |
|---|---|
| `app/domain/documents.py` | Defines `Attachment` (a saved file ID and its purpose), `DocumentPage` (text, page number, reading method), and `DocumentEvidence` (filename, checksum, timestamp, pages, and warnings). `source(page)` returns a stable citation such as `document:...#page=2`. Shared constants bound file size, page count, and extracted text. |
| `app/connectors/documents/extractor.py` | `extract(bytes, extension, languages)` returns checked pages and visible warnings. PDFium reads PDF text; Pillow decodes images; `recognize_image()` runs Tesseract. `office_text()` reads DOCX/ODT text without following external references. `VisibleHTML` omits script/style content. Unsupported, encrypted, malformed, binary, or oversized inputs fail clearly. |
| `app/connectors/documents/worker.py` | Runs one extraction in a separate process. Takes a saved local path, format, and OCR languages; writes a bounded JSON result. CPU and Linux memory limits keep parsing separate from the application process. |
| `app/storage/documents.py` | `DocumentRow` stores file metadata, extraction state, text, warnings, and errors. `document_record()` returns a saved record. Original bytes live under the data directory's `uploads/` folder. |
| `migrations/versions/v002_documents.py` | Adds the uploads table while preserving existing runs, contacts, and connector credentials. Startup applies this after the earlier service migration. |
| `app/services/documents.py` | `save()` checks and stores bytes, returning the file record and extraction job. Identical uploads reuse their content identity and extraction. `extract()` runs the isolated reader with a 90-second limit and an environment without provider credentials. `get()`/`list()` return owner-visible results. `recover()` marks interrupted work; `retry()` queues an explicit retry. |
| `app/services/application.py` | Owns `DocumentService`, executes document jobs on the same single worker, validates attached file IDs, and includes file status in run details. Uploading a file does not start outreach or contact a model. |
| `app/agent/nodes/documents.py` | `prepare_documents()` loads ready sources into the saved run before interpretation, and adds background text to the sender context. `evidence_records()` pairs each page's text with its filename, purpose, and citation. `bounded_evidence()` returns complete JSON excerpts with space for every source, including escaped text; it reports shortening. |
| `app/agent/graph.py` | Adds the document-loading step before goal interpretation in the research subgraph. Saved checkpoints preserve loaded evidence. |
| `app/agent/nodes/goal.py`, `components/goal_interpreter.py`, `prompts/goal.py` | Pass bounded file evidence into the existing interpretation call. The model can use relevant topics and skills as search signals while preserving your original goal. File text is treated as evidence, never as instructions to change approvals, tools, or contact rules. |
| `app/agent/nodes/discovery.py` | Combines research-file text with supplied notes, keeping filename/page citations. Divides a bounded evidence allowance across pages so a single long file does not consume all available space. |
| `app/agent/nodes/recipients.py` | Collects addresses present in cited research uploads. Addresses from private files require explicit owner selection; public-page discovery keeps its existing rules. |
| `app/domain/workflow.py`, `storage/checkpoints.py` | Add attachment references and extracted documents to workflow state, with serialization support for saved/resumed runs. Old runs default to empty file collections. |
| `app/connectors/telegram/client.py` | `download_file()` uses Telegram's file API with bounded downloads and sanitized errors; `FakeTelegram` supplies local file bytes for tests. |
| `app/connectors/telegram/bot.py` | Accepts owner documents/photos during a new goal, saves purpose choices, and keeps conversation progress. `/files`, `/clearfiles`, and `/retryfile FILE_ID` inspect or manage the current attachments. Repeated updates reuse saved extraction. |
| `app/web/routes/control.py` | Adds authenticated upload, status, inspection, and retry routes. Uploads stream with a 10 MiB ceiling and return HTTP 202. Connector status reports OCR availability. |
| `app/web/static/index.html`, `app.js`, `app.css` | Add the upload area, per-file purpose choices, extraction status, text preview, remove/retry controls, source links, and file evidence in run details. External file content is rendered as text. |
| `app/settings.py`, `.env.example` | Read `OUTREACH_OCR_LANGUAGES` (default `eng`) for installed OCR languages. |
| `app/main.py` | Recovers interrupted document extraction during startup. |
| `app/demo.py` | Keeps fictional goal interpretation compatible with document context. Demo document parsing/OCR is real and local; its model/search/Gmail remain simulated. |
| `pyproject.toml`, `Dockerfile` | Add PDFium/Pillow dependencies and install English Tesseract in the container. Local OCR installation is described in setup. |
| `tests/test_documents.py` | Checks real PDF text/page numbers, text/office/HTML formats, extraction limits, malformed files, optional real image/scanned-PDF OCR, upload authentication, saved-job recovery, duplicate uploads, document-driven search, recipient confirmation, and Telegram downloads. It also checks large Unicode pipe output, saved background evidence, complete source references under input limits, and parser cancellation without exposing provider keys. |
| `tests/test_telegram.py` | Runs the complete guided conversation with either public-browser evidence or an uploaded file. File reading finishes before research, and the shared approval creates exactly one simulated Gmail draft without repeating model calls. |
| `tests/test_server_recovery.py` | Updates migration checks to the new schema revision while still verifying old contact data survives. |

The feature's completed checks and limits are recorded in [validation](docs/VALIDATION.md) and [setup](docs/SETUP.md). Current limits are five files per run, 10 MiB per file, 20 pages/frames per file, 16 megapixels per input image, and 40,000 extracted characters per file. Interpretation shares up to 20,000 text characters across files; research combines notes/file excerpts within 80,000 serialized characters before web evidence. Clipping and OCR methods are visible when you inspect the text. Files are saved across restarts; removing one from a new-run form does not delete saved originals or historical runs.

`README.md`, `docs/SETUP.md`, `docs/API_GUIDE.md`, `docs/VALIDATION.md`, `plan.md`, and `CONTRIBUTING.md` were updated with file usage, the OCR installation step, authenticated upload requests, and reproducible checks. `docs/assets/workflow.mmd` and its SVG now show local file reading before goal interpretation.

## Phase 38 — Prepare Gmail and clarify browsing without Brave

The Gmail connector was already built in phase 33. This follow-up prepares its configuration and makes the sign-in steps easier to follow; it does not claim that the owner's Gmail account has been connected.

- `docs/SETUP.md` now walks through Google Cloud project creation, enabling Gmail, choosing the consent audience, adding a test user, requesting the two Gmail permissions, and creating a **Web application** OAuth client. It gives the exact callback URL and explains saving client credentials in `.env`, restarting, signing in through Connections, and checking the connected address. It also explains how **Public URLs** reads websites without a Brave key, with the existing page/depth limits.
- `.env.example` now explicitly says it is tracked by Git and must contain no real passwords or keys. It remains a shareable list of setting names and defaults.
- The local `.env` was created from the user's configuration and excluded from Git. Credentials were removed from the tracked template, and a local encryption key was generated for saved Gmail tokens. Gmail reading is enabled; sending remains disabled. The actual values are never documented or committed.
- Verification: 58 existing checks in `tests/test_gmail_oauth.py`, `tests/test_browser.py`, and `tests/test_researcher.py` passed. They check encrypted tokens, renewal, account/consent validation, browser restrictions, and grounded research. A real browser request retrieved a public page without Brave; no Gmail account was accessed. The local environment parsed correctly, its encryption key was valid, and `.env` was ignored by Git with owner-only file permissions.

**Still needed from the owner:** create the Google client, enter its client ID and secret in `.env`, and finish Google's consent page. A successful connection must display the actual Gmail address in Connections before it is treated as working.

## Phase 39 — Talk normally in Telegram

Previously, any ordinary message became either an outreach goal or an answer to a form question. This phase adds a conversation layer before outreach. You can now say “Hi,” ask about an uploaded PDF, provide a website to investigate, or ask a follow-up without starting a new run or entering `/new`.

The model chooses between answering and a small set of reading tools. **Read-only** means those tools can retrieve information but cannot approve messages, send email, run terminal commands, or change accounts. When you actually want outreach, the conversation prepares a request for you to start. Research, qualification, contact checks, writing, review, and exact-message approval then follow the existing workflow. A background file can be discussed in chat while remaining separate from the evidence used to identify prospects.

| New or changed file | Purpose, main inputs, and outputs |
|---|---|
| `app/domain/conversation.py` | `ConversationAction` checks a model's suggestion: reply, search, read a page, read an attached file, inspect an outreach run, or propose outreach. Its input is model-generated JSON; its output is a validated record. Unknown actions such as `send_email` are rejected. |
| `app/agent/prompts/conversation.py` | `CONVERSATION_INSTRUCTIONS` explains normal dialogue, follow-ups, choosing tools, citing evidence, and asking only necessary questions. File/page text is evidence, not an instruction to the application. Python enforces the actual permissions and limits. |
| `app/agent/conversation.py` | `build_conversation_graph()` connects `decide`, `read_tool`, and `answer`. `decide()` takes the latest message, recent history, available tools, and gathered evidence; it returns a checked action. `read_tool()` adds an observation. `answer()` returns text and an optional outreach proposal. The loop stops at the configured limit even if the model keeps requesting tools. |
| `app/services/conversation.py` | `queue()` accepts a message, conversation ID, file references, and repeat-protection key; it returns a saved job. `execute()` runs that job through LangGraph, saves the answer, and queues a Telegram reply. `_remember()` retains six completed exchanges. `read_tool()` dispatches bounded search/browser/file/status reads. `_page_depth()` permits owner-supplied/search URLs and one level of same-site links. `response()` attaches known citations and builds a concrete outreach proposal. `start_proposal()` starts that exact request through `AgentService`, once, only while it is current. |
| `app/connectors/telegram/messages.py` | `queue_message()` takes text and optional buttons, splits long replies within Telegram's Unicode limit, and saves outgoing parts. It does not contact Telegram itself. Repeated message keys reuse existing outgoing records. Buttons appear only on the last part. |
| `app/connectors/telegram/bot.py` | Ordinary messages and file captions now queue conversation work. `/new` resets context, `/guided` opens the optional form, and `/chat` returns to normal messages. `_chat_conversation()` preserves current attachments when leaving old guided state and chooses the same conversation identity when a saved update is replayed. Existing review/edit/recipient controls remain. |
| `app/services/application.py` | The single worker also executes chat jobs. Retry sends them back to the conversation service, rather than accidentally starting outreach. Failures tell the owner how to retry without exposing provider errors. File-ready notifications now invite questions about the file. |
| `app/storage/control.py` | `enqueue()` can label a record as `chat` and save its latest-turn marker in the same transaction. A follow-up makes an older outreach-proposal button stale. Existing tables hold this data, so no new database or migration is needed. |
| `app/services/limits.py` | Adds `max_chat_model_calls` (six by default) and `max_chat_tool_calls` (five). Existing search, browser, timeout, cancellation, and estimated-cost controls still apply. Calls already spent are counted when a failed turn is retried. |
| `app/demo.py` | The fake model recognizes conversation requests and returns an explicitly simulated answer. Use `/guided` for the existing fictional outreach walkthrough. This demonstrates application behavior, not real model understanding. |
| `tests/test_conversation.py` | Eighteen checks cover ordinary messages, follow-up context after reopening SQLite, optional reset, queued message order, duplicate updates, extraction before answering a file caption, file access, sourced web answers, missing Brave, URL/depth limits, budget persistence, cancellation, failure recovery, bounded history, and starting the existing approval flow from a conversation proposal. |
| `tests/test_telegram.py` | Retains the complete guided browser/file → review → simulated Gmail flow under `/guided`. Existing tests still check owner access, restart behavior, stale buttons, message lengths, and delivery limits. |
| `tests/test_documents.py` | Updates the upload/restart check for normal chat. A file with a question in its caption attaches to the saved conversation and queues reading before answering. |

For example, a PDF captioned “Summarize this” first enters the local file-reading queue. A chat job follows it, reads the extracted text, and answers with filename/page references. “Explain the second point” uses recent history and source excerpts. It does not require an outreach goal, recipient, or email draft.

Messages, answers, and bounded source excerpts live in SQLite. Chat does not checkpoint each intermediate model decision: after interruption you explicitly retry the saved turn, keeping recorded budgets and cached page reads. An answer already saved before interruption is reused. `/new` starts a fresh context; it does not delete historical records or cancel saved outreach runs. Chat jobs and costs appear in dashboard job/usage statistics; a dashboard chat transcript interface has not been added.

`README.md`, `docs/SETUP.md`, `docs/API_GUIDE.md`, `plan.md`, and the Mermaid/SVG diagram describe this working route. `docs/VALIDATION.md` records 376 passing tests including local Chromium/OCR, plus the four simulated outreach evaluations. Live Telegram delivery and Groq's conversational quality still require an account-connected test; no real messages or Gmail actions were sent during these checks.

## Phase 40 — Explain failed model calls and reserved budget

The old generic Telegram failure did not distinguish a blocked model from an invalid key or an exhausted budget. A bounded live diagnostic returned Groq's `403 model_permission_blocked_org`: the key was accepted, but the organization did not allow the configured model. Two earlier failed attempts had added `$0.10` to the app's fixed reservation counter; that counter was not an invoice.

| Changed file | What it now explains or does |
|---|---|
| `app/llm/client.py` | `ModelProviderError` accepts a known provider/reason/status and returns safe, fixed explanation text. Unknown provider text cannot become a user-facing message. |
| `app/llm/groq_client.py` | `_request_failure(response)` identifies key, permission, request, rate-limit, and server failures. Organization and project blocks have distinct explanations. |
| `app/agent/context.py` | `generate_structured()` saves the safe reason and HTTP status with the failed attempt. It retries temporary connection/server failures once, and stops immediately for known configuration or rate-limit failures. |
| `app/services/conversation.py` | `execute(job)` saves the safe provider explanation with a failed chat turn so the owner can inspect it later. It still keeps inputs and budgets for explicit retry. |
| `app/services/application.py` | `execute_one()` puts that explanation in the failed job and Telegram notification. Application limits have their own explanation; arbitrary exception messages remain hidden. |
| `app/web/static/app.js` | The overview and run details say **Reserved model budget** and **model attempts**. They explain that failed attempts count and that the displayed amount is not money owed. No provider billing data is inferred from this number. |
| `tests/test_groq_client.py` | Checks safe explanations for HTTP failures, malformed error bodies, hidden credentials, and exactly one request per adapter call. |
| `tests/test_conversation.py` | Runs simulated provider failures through the real chat worker. Verifies the saved reason reaches Telegram and dashboard data, blocked calls are not repeated, transient server failures get one retry, and reservations stay counted. |
| `docs/SETUP.md`, `docs/VALIDATION.md` | Explain permission recovery, provider billing versus application reservations, and the checks actually completed. |

**Checked:** 391 automated tests passed, including local Chromium/OCR, plus JavaScript syntax and Git whitespace checks. Tests use fake external services. The live diagnostic identified the permission block; successful live conversation remains unverified. Credentials, model selection, and saved data were preserved.

### After phase 40 — Prepare the xAI key fields

This earlier change added a labeled xAI/Grok section to `.env.example` and the local `.env`, with `XAI_API_KEY`, `XAI_MODEL=grok-4.3`, and `XAI_REASONING_EFFORT=none`. At that point these fields were preparation only and did not change the selected provider. Phase 41 below implements the connection.

The xAI Console controls the key's requests/tokens per minute, expiry, credit balance, and billing limits. Adding environment fields does not change those account controls. Verification parsed both files, checked that all existing local values were preserved, and confirmed that `.env` remains ignored and untracked. No model calls or credential changes were made.

## Phase 41 — Use Grok in Telegram and outreach

The selected provider is now connected to the real application. With `OUTREACH_MODEL_PROVIDER=xai`, a Telegram message passes through the existing saved job queue and conversation graph to `XAIModelClient`. Outreach uses that same adapter for its research reasoning, qualification, writing, and review. The browser, file reader, Gmail checks, and approval process still run in the application.

| Changed file | Purpose in this phase |
|---|---|
| `app/llm/xai_client.py` | Converts our instructions and requested record format into one xAI Responses request. `grok-4.3` and reasoning `none` are the starting settings. JSON means structured text that Python can validate before using it. There are no hidden adapter retries or xAI-hosted research tools. |
| `app/llm/client.py` | Adds xAI to the known provider names and adds safe explanations for missing credits and denied xAI access. Raw errors and keys never become public messages. |
| `app/settings.py`, `app/services/runs.py` | Accept and select `xai`, open its client only when needed, pass existing timeout/output limits, and close its connection. Missing xAI configuration raises a useful error instead of switching providers. |
| `app/web/routes/control.py` | `connections(request)` checks the selected provider's key when returning dashboard status. It returns a boolean, never the key. “Configured” means present, not verified by a live call. |
| `.env.example`, local `.env` | Select xAI explicitly. The template contains no real key. The local file preserves the entered key and removes an empty duplicate that was overriding it. Other credentials and local data are preserved. |
| `tests/conftest.py`, `tests/test_xai_client.py` | Isolate xAI credentials and check valid/invalid responses, token counts, model selection, Telegram greetings and duplicate updates, saved failure explanations, retry counts, dashboard status, and outreach approval. |
| `README.md`, `docs/SETUP.md`, `docs/VALIDATION.md`, this guide | List the working adapter, explain its settings and restart steps, distinguish provider bills from reserved budgets, and record offline versus live checks. |

The existing per-call reservation remains a local budget estimate, not xAI pricing. The configured output limit bounds visible text; increasing reasoning above `none` can use additional tokens. Provider credit, spending, and key rate limits remain in xAI Console.

**Checked:** all 425 tests passed, including local Chromium/OCR and the simulated evaluations. The focused provider/conversation/dashboard checks passed 102 tests. No live model call or real Telegram/Gmail message was made. See [validation](docs/VALIDATION.md); live xAI credentials, credits, permissions, and reply quality still need the owner's first Telegram request.

**Restart troubleshooting:** a later Telegram failure came from a server process started before the xAI changes. Its authenticated Connections response still reported `groq`, despite `.env` selecting `xai`. `docs/SETUP.md` now explains that editing files does not reload a running service, how to check the active provider, and why old failed jobs remain in history. `docs/VALIDATION.md` records the graceful restart: health passed, the active provider became `xai`, Telegram connected, and the failed run remained saved. The queue was paused during checks and restored afterward; no paid model request was made. This is an operating instruction, not a new workflow phase or a change to credentials.

**Account-access troubleshooting:** the next owner-triggered retry reached xAI but received `403`, meaning access was denied. A read-only key-status check accepted the key and confirmed its model/endpoint permissions, while reporting `team_blocked: true`. `docs/SETUP.md` explains that this flag belongs to the xAI team and does not reveal whether credits or another account restriction caused it. `docs/VALIDATION.md` records the confirmed flags and the remaining live check. The application stopped after one attempt; its budgets and credentials were not changed. No additional model generation was requested during this diagnosis.

## Phase 42 — Supabase state and requested Gmail drafts

This phase changes the current email behavior: the agent prepares emails only after your instruction and the **Start outreach** action. A search or file question remains conversation. Requested drafts pass contact checks and automated review, are saved in Gmail, and trigger a notification. You review, edit, and send them in Gmail. No agent action can send. Older phase descriptions above record what worked at that time; they do not override this policy.

Supabase is an optional home for the existing state. It uses one PostgreSQL database for application tables and LangGraph checkpoints. No extra Supabase API key, new login system, or file-storage service was added. A schema is a named group of tables; ours is called `outreach` and stays outside the public Data API. Row-level security and removed browser-role grants protect these tables, while the authenticated Python server connects as their owner.

| New or changed file | Main inputs, outputs, and connection to the application |
|---|---|
| `app/settings.py` | `from_env()` reads the optional `OUTREACH_SUPABASE_DATABASE_URL`. `use_one_supabase_database()` converts it into both database adapter settings and selects Postgres checkpoints. It rejects conflicting URLs and hides database credentials in printed settings/errors. The old sending environment switch is ignored; `sending_enabled` can only be false. |
| `app/storage/postgres.py` | `connection_urls(text)` checks and converts the copied URL without printing it. It requires encrypted remote connections and rejects transaction pooler port 6543. `prepare_connection()` selects the private schema. `protect_tables(engine)` removes Data API access and enables row-level security. `database_instance_lock(engine)` holds a database lock so a second host cannot start another worker against the same records. |
| `app/storage/database.py` | `create_database()` now accepts `private_schema=True` for Supabase, applies existing migrations, and limits open Postgres connections. It returns a SQLAlchemy engine, the application's database connection manager. |
| `app/storage/checkpoints.py` | `open_checkpointer()` opens a session to the same private schema for LangGraph. A checkpoint contains the run's saved progress; it is separate from the job record that tells the worker what to execute. |
| `app/services/runtime.py` | `open_runtime()` uses the configured store, holds the database instance lock, opens the checkpoint connection, and protects all tables including those created by LangGraph. It closes these resources together. |
| `app/main.py` | Demo configuration clears the Supabase setting and uses its separate local SQLite files, preventing a fake walkthrough from writing to the real cloud database. |
| `app/domain/workflow.py` | `WorkflowRequest` accepts `none` or `draft` as destinations; new `send` requests fail validation. `WorkflowState` still reads historical send records. `Outcome.message_fingerprint` records the exact saved account, recipient, message, and action; it does not pretend the owner already reviewed the email. |
| `app/agent/prompts/conversation.py` | Explains that drafting needs an explicit request. “Find opportunities” uses research tools; “Create email drafts” can propose outreach. It tells the model to explain the configured batch limit and ask about a smaller batch instead of promising ten emails when only five prospects are allowed. |
| `app/services/conversation.py` | `execute()` supplies the actual draft limit and disabled sending capability to the conversation model. `response()` shows the destination and batch limit. `start_proposal()` remains the only conversation handoff to drafting and prevents repeated button clicks from duplicating runs. |
| `app/agent/nodes/approval.py` | `prepare_approval()` lets requested Gmail drafts continue after automated review. App-only drafts and old paused decisions keep their previous review controls. No fabricated human approval is saved. |
| `app/agent/nodes/external.py` | `external_node()` saves reviewed drafts only after account and contact checks. It records a fingerprint and Gmail draft ID, reuses confirmed results on replay, and keeps uncertain writes blocked. Saving a draft does not update “last contacted,” since nobody has received it yet. |
| `app/services/runs.py` | `validate_request()` rejects agent sending even for internal callers that bypass normal input validation. `_execute()` also blocks resuming legacy send-mode records before any model or Gmail call. |
| `app/connectors/gmail/oauth.py` | `ConnectedGmail.send()` and `BoundGmail.send()` refuse immediately, without requesting tokens or contacting Google. Draft creation still uses the existing encrypted credentials and account lock. The low-level protocol client's old send method remains for historical tests but is not reachable through the connected agent. |
| `app/services/application.py` | `execute_one()` counts confirmed draft outcomes and queues a notification with recipient/subject details and the Gmail Drafts link. It tells the owner to review, edit, and click Send manually. |
| `app/connectors/telegram/bot.py` | Guided setup offers Gmail drafts or app-only drafts, with no send option. Help explains request-only drafting. `/review` points to Gmail for completed drafts and retains old pending review controls. |
| `app/web/routes/control.py` | `connections()` returns the storage backend, checkpoint type, and schema name without returning the URL. This lets the owner verify whether SQLite or Supabase is active. |
| `app/web/static/index.html`, `app.js` | The request form labels draft destinations and removes sending. Connections shows **Saved state**. Completed draft runs show **Open Gmail Drafts** and manual review instructions. The old sent counter is labeled as historical; manual Gmail sends are not inferred from saved drafts. |
| `evals/scoring.py` | `score_run()` checks saved drafts against their account/message fingerprint, automated review, and contact decision. Missing support or any agent-send outcome lowers the workflow-rule score. |
| `Dockerfile` | Installs the existing `postgres` dependency extra so the packaged service can use the same Supabase configuration. The container image itself still needs a Docker-capable host for a build check. |
| `.env.example`, local `.env` | Add one blank optional Supabase URL. The shared template removes the old sending switch. Local credentials, operating limits, and database files are preserved; the local environment file is never committed. |
| `docs/SUPABASE.md` | Project creation, session-pooler URL, startup, connection verification, state explanation, and backup instructions. It clearly states that SQLite records are preserved but not automatically migrated. |
| `README.md`, `docs/SETUP.md`, `docs/API_GUIDE.md`, `docs/VALIDATION.md`, `docs/assets/workflow.mmd`, `workflow.svg` | Describe the current draft-only flow and storage choices. The diagram shows human review and sending outside the agent. Validation distinguishes real local Postgres from a cloud account connection. |

For example: “Create outreach drafts for these five companies” → owner starts the proposal → sources and contact checks → automated draft review → saved Gmail drafts → notification → owner reviews/sends in Gmail. Qualification, recipient evidence, and budgets can result in fewer drafts; the app never increases spending limits to meet a requested count.

| Changed tests | What they check in everyday language |
|---|---|
| `tests/test_supabase_storage.py` | URL validation and secret hiding; real temporary Postgres stores jobs/checkpoints and resumes a paused run after reopening; another service is blocked; browser roles cannot access private tables; a saved Gmail draft is reused after restart instead of being created twice. The database is local and disposable, with no cloud credentials. |
| `tests/test_full_workflow.py` | Requested Gmail drafts need no extra app approval. Failed review and contact opt-outs prevent creation. Replaying a draft reuses its result; uncertain writes stay blocked. Old sending flags and saved send-mode runs cannot send. |
| `tests/test_full_api.py` | The authenticated API rejects `gmail_action: "send"` before queuing work. |
| `tests/test_gmail_oauth.py` | Account changes block draft writes. Both connected send methods fail before any HTTP request, even with expired credentials. |
| `tests/test_conversation.py` | An email proposal creates nothing until the owner starts it. Repeated starts create one run; completion produces one draft and manual-send guidance. The model receives the actual batch limit. Existing ordinary-chat/file checks still show no automatic outreach. |
| `tests/test_telegram.py` | Guided browser/file flows save requested fake Gmail drafts, return the same saved run through dashboard data, notify the owner, and ignore repeated starts. |
| `tests/test_service.py` | Counts a draft only after Gmail confirms creation; no send or invented human-approval count is added. |
| `tests/test_server_recovery.py` | Cancellation during draft creation lets the in-flight result finish recording before stopping. |
| `tests/test_evaluations.py` | Wrong accounts/actions, missing review records, and agent sends fail the workflow checks. |

**Available now:** local SQLite and optional Supabase configuration, durable state, explicit requested drafts, owner notifications, and manual sending. **Still account-dependent:** creating your Supabase project, adding its URL, connecting Gmail in the selected store, and resolving the model provider's account access. Existing SQLite records are not migrated by this change. Additional orchestration/approval features have not been added. Completed checks are recorded in [validation](docs/VALIDATION.md).

## Phase 43 — Model roles and native tool calls

A model role means the kind of work we ask a model to do. With xAI selected, 4.3 understands instructions and writes messages, 4.20 handles reasoning and chooses tools, and 4.20 Multi-Agent analyzes research evidence. A greeting can finish after one 4.3 call. Models are selected by the application, not by model-generated code. These are the owner's requested roles; comparative quality measurements have not been claimed.

| New or changed file | Purpose, main inputs, and outputs |
|---|---|
| `app/llm/xai_routing.py` | `role_for(record_type)` assigns a role. `configured_models()` reads non-secret model names. `XAITaskRouter.generate_structured()` takes instructions, evidence, and an expected record type, calls the corresponding model, and returns the validated record. `_select_tool()` accepts exactly one permitted native function call or a final answer. Clients are opened lazily and closed together. Research uses four agents and no provider-hosted search tools. |
| `app/llm/tools.py` | `tool_definitions(inputs)` advertises available reading tools. `checked_call()` validates a returned name, identifier, and exact argument fields. `function_history()` pairs saved calls with their results so the next reasoning call can use them without provider-hosted conversation storage. For example, a `read_file` request must contain an attached document's ID, never a filesystem command. |
| `app/llm/xai_client.py` | `request(body)` performs one HTTP request and reads safe usage fields, including reasoning tokens when available. `parse_structured()` validates ordinary JSON records and rejects unexpected tool output. The reasoning-effort parameter can be omitted for 4.20. The previous single-model adapter remains available. |
| `app/domain/conversation.py` | `ConversationInstruction` identifies the first 4.3 pass. `ConversationAction` adds research analysis and a call ID used to match tool results. An instruction-pass tool suggestion is checked by the reasoner before execution. |
| `app/domain/research.py` | `ResearchAnalysis` holds a summary and exact source references. It describes an analysis of collected text, not proof that the model independently visited a page. |
| `app/agent/conversation.py` | `understand()` uses 4.3 for the initial instruction pass when routing is enabled. `decide()` selects tools or a final response with the reasoning model and leaves room in the call budget for analysis and an answer. Other providers keep their single-model loop. |
| `app/agent/context.py` | The managed model wrapper exposes routing capability and adds role/model information to call events, including failures. Every routed and nested research call still reserves the existing budget. |
| `app/services/conversation.py` | `read_tool()` can analyze already collected evidence, rejects invented source references, and records a tool ID, duration, outcome, and source count. It retains native call/result pairs for the next reasoning request. Search, browser, file, and Gmail restrictions remain enforced by their services. |
| `app/agent/prompts/conversation.py` | Explains when research analysis is useful and requires collecting evidence first. Email drafting still needs an explicit owner request. |
| `app/services/runs.py` | `real_model_client()` selects the new router for xAI and opens it only when a model call is needed. `RunManager` also retains its checkpointer for use by the conversation graph in the following phase. |
| `app/settings.py`, `.env.example`, local `.env` | Enable xAI task routing and name the three models. The local update preserved all credentials and other settings. `XAI_TASK_ROUTING=false` keeps the previous single-model path for troubleshooting. `.env` is ignored and never committed. |
| `app/web/routes/control.py`, `app/web/static/app.js` | Connections displays the configured role-to-model mapping. This checks configuration presence, not live model permissions or credits. |
| `tests/test_model_routing.py` | Fake HTTP responses pass through the real conversation/outreach graphs. Tests check the role sequence, function-call arguments, matching results, research sources, budgets, and rejection of unknown, unavailable, duplicate-batch, or malformed tools. No paid requests occur. |
| `tests/test_xai_client.py` | Existing single-model compatibility tests explicitly select that mode; new routing behavior has its own tests. |
| `docs/MODELS_AND_TOOLS.md`, `docs/SETUP.md`, `README.md` | Explain the working model roles, tool flowchart, configuration, limitations, and how to inspect events in plain language. |

**Checked:** focused routing, provider, conversation, outreach, checkpoint, API, and shared-service suites passed; dashboard JavaScript syntax passed. Native calls use mocked HTTP, with no real Telegram/Gmail messages or paid inference. Live quality and provider access remain account-dependent. Search discovery still needs Brave; file/URL reading and research analysis can work without it. Chat checkpoint recovery and natural-language continuation are the next change, not part of this phase's completion.

## Phase 44 — Remember stopped work and continue it

State management now covers intermediate chat steps as well as outreach. State means the saved information needed to keep working: the original request, current action, collected evidence, and what comes next. A checkpoint is a saved snapshot of that state. For example, if a page has been read and the next model call fails, **continue** resumes with that page's text already available. Unfinished task links remain available even after many later questions; only the index of completed tasks is shortened.

**Working behavior:** say **stop** to pause at a safe boundary and **continue** to resume. Both commands also accept an explicit ID: `/stop RUN_ID`, `/continue RUN_ID`. If the application itself stops, restart it before continuing. Several unfinished tasks require choosing one. A recipient/review pause still requires its actual decision. Completed tasks are not restarted. `/cancel RUN_ID` remains a permanent cancellation; `/new` starts a separate conversation.

| New or changed file | Purpose, main inputs, and outputs |
|---|---|
| `app/services/tasks.py` | `remember(session_id, run_id)` links saved work to its Telegram conversation. `select()` finds one task or explains ambiguity. `stop(run_id)` saves a resumable stop flag and removes queued execution from the worker's active queue. `continue_task()` reads the checkpoint and returns a queued job or a plain explanation of the pending decision/status. It retains the run ID and never changes recipients, approvals, Gmail account bindings, or budgets. |
| `app/agent/conversation.py` | `ConversationState.inputs` saves the original message/context. `build_conversation_graph(checkpointer)` now saves each instruction, decision, reading, and answer step. Each step logs its name and uses a distinct cache scope so a new decision is not confused with retrying the old one. |
| `app/services/conversation.py` | `config(run_id)` uses a separate `chat:RUN_ID` checkpoint thread. `execute()` resumes the saved graph with its original inputs and observations. `_save_progress()` records the next step and count of retained tools in everyday dashboard data. `read_tool()` caches completed results before the next graph checkpoint. `queue()` and `start_proposal()` register the conversation's tasks. Completed answers and notifications continue to reuse their existing records. |
| `app/agent/context.py` | The managed model wrapper caches each validated response by run, task, exact input/schema, and workflow revision. This prevents repeating finished calls inside a step interrupted before its next checkpoint. Search results are cached by run/query. A cache is simply a saved result. Cache hits are logged separately and do not reserve another paid call. Failed requests are not cached. |
| `app/agent/graph.py` | `observed()` assigns a cache scope using the node name and revision/version counters. Intentional re-reviews still run even if the draft text is unchanged. A context variable keeps concurrent work from mixing scopes. |
| `app/agent/nodes/common.py` | `for_each()` lets in-flight prospect operations finish recording their results before propagating a stop/cancel. A stop does not become a failed qualification or review result. |
| `app/services/cancellation.py` | `RunStopped` means resumable stop. `check_cancelled()` checks both that flag and permanent cancellation at existing safe boundaries. It does not interrupt a Gmail write midway through recording its outcome. |
| `app/domain/workflow.py` | Adds `stopped` as a valid progress value so saved stopped runs can be read and resumed normally. |
| `app/services/runs.py` | `_execute()` saves stopped outreach progress and waits for each checkpoint to be durable before advancing. Retrying a completely finished checkpoint only saves its result. Pending graph interrupts still require recipient/review decisions. |
| `app/services/application.py` | Installs the shared task controller, allows retry of stopped work, records stopped job/run status, and returns saved progress in run details. Stop and continue use the same worker as normal execution. Returning to an older chat task makes its newly produced proposal current again; later messages still invalidate stale proposals. |
| `app/connectors/telegram/bot.py` | `_task_command()` recognizes short phrases such as “please continue,” “resume,” and “stop” without spending a model call. Guided outreach now retains its conversation/task link after starting. Help explains the new controls. Unauthorized updates still cannot reach these handlers. |
| `app/web/routes/control.py`, `app/web/static/app.js` | Add owner-protected stop/continue endpoints and dashboard buttons, stopped counters, and a saved-next-step display. A continuation waiting for a decision returns an explanation rather than queuing work. |
| `tests/test_task_continuation.py` | Reopens real SQLite checkpoints after a model failure and continues through Telegram with the same request/evidence/budget. Also checks stop during a read, recovery between result saving and checkpointing, queued stops, duplicate continuation, ambiguous tasks, recipient/review pauses, permanent cancellation, exhausted budgets, outreach continuation, retention after many later questions, renewed proposal freshness, and owner authentication. |
| `README.md`, `docs/SETUP.md`, `docs/API_GUIDE.md`, `docs/MODELS_AND_TOOLS.md` | Explain how to stop, resume, inspect progress, and distinguish resumable stop from permanent cancellation. API documentation describes when a continue response includes a new job. |
| `docs/assets/workflow.mmd`, `docs/assets/workflow.svg` | The editable flowchart and rendered README image now show model roles, saved conversation evidence, and continuing the same task. |
| `docs/VALIDATION.md` | Records the completed checks and distinguishes local/fake verification from live provider/account testing. |

The existing application tables store task links, stop flags, and cached results; the existing SQLite or Postgres checkpointer stores graph snapshots. No new database, migration, or key is required. Network calls interrupted before saving a result may be repeated. Uncertain Gmail writes remain blocked. Old chat jobs created before this phase do not acquire missing historical checkpoints; they can retry from their saved input. Model failures caused by account access or exhausted budgets must still be resolved; “continue” never resets spending.

**Checked:** the full 470-test suite passed with real local Chromium, OCR, and temporary Postgres checks enabled, including the new restart scenarios. Four simulated evaluations passed. JavaScript syntax and Git whitespace checks passed. No paid inference or real Telegram/Gmail message was sent. The real server needs a restart to load these changes; a live xAI conversation still depends on account credits and model access. A broader validation dashboard remains later work.

## Phase 45 — Supabase originals, semantic search, and storage validation

This phase connects the existing state-storage design to a private file bucket and a searchable owner library. PostgreSQL stores tasks and LangGraph checkpoints; pgvector searches saved passages by meaning; Supabase Storage holds original file bytes. One Supabase project provides both services. The Python service continues to run the agent.

You create the Supabase project and enter its database URL, HTTPS project URL, and backend secret key privately in `.env`. `python -m app.setup_storage --download-model --fresh-start` then creates tables, extensions, indexes, and the private bucket, while backing up local test data. It preserves Telegram's processed-update cursor so old messages are not restarted. Later setup runs omit `--fresh-start`. The code works with local substitutes before cloud credentials are entered; that does not establish that a cloud account is connected.

An **embedding** is a list of numbers representing a passage's meaning. The English BGE model runs locally through FastEmbed, producing 384 numbers per passage. It needs a one-time public model download, CPU time, and disk space; it needs no embedding API key. Existing Grok calls still use their normal provider account. Images enter the library through OCR text; this phase does not compare visual image features.

For example, an uploaded CV may say “Built API observability systems.” A later question about “monitoring slow requests” can retrieve that passage even when the words differ. Search combines vector similarity with keyword ranking, returns up to five passages, and preserves filenames/pages, URLs, source hashes, dates, and background/research roles. Matches are evidence candidates, not guarantees of truth. Historical web pages may need refreshing.

### New and changed files

| File | Purpose, main inputs and outputs, and connections |
|---|---|
| `.env.example`, ignored `.env` | Keep the active xAI, Telegram, Gmail, browser, Supabase, and usage fields. Remove redundant defaults and empty legacy database fields. Preserve real credentials and customized limits. An ignored `.env.before-supabase-cleanup` recovery copy keeps the previous local configuration. |
| `app/settings.py` | Read the project URL, backend secret, file backend, and semantic-search switch. Validate the cloud file configuration before use. Hide database and storage credentials from settings output. The existing single database URL still selects PostgreSQL for both records and checkpoints. |
| `app/setup_storage.py` | `setup()` takes settings and optional download/fresh-start flags, provisions resources, and prints safe validation outcomes. `backup_local()` copies stopped-service SQLite records and originals and returns the saved Telegram cursor. Setup uses the existing service lock and never deletes cloud records or calls Grok/Gmail. |
| `app/storage/files.py` | `LocalFiles`, `SupabaseFiles`, and `FakeFiles` implement asynchronous original-file writes, reads, and deletion. `ensure_bucket()` creates/checks the private bucket and file limit. Supabase uses the backend key only on its own endpoint and refuses redirects. Lost upload responses are reconciled against the existing object's checksum. |
| `app/storage/documents.py` | Add the original's backend and object key to each document record. Earlier documents default to local storage, so changing configuration does not silently reinterpret their paths. |
| `app/services/documents.py` | `save_async(filename, bytes)` confirms cloud persistence, saves metadata, and queues extraction. The existing synchronous `save()` remains for local callers. `original(id)` returns checksum-checked bytes. `extract(id)` uses a restricted temporary file, runs the existing parser/OCR process, removes the temporary file, and queues knowledge indexing. `list()` now reads metadata in one query. |
| `app/llm/embeddings.py` | `LocalEmbeddings.prepare()` loads the cached BGE model or permits its initial download during setup. `chunks(text)` splits within a page using actual token offsets; `passages(texts)` and `query(text)` return validated vectors. A small lock protects the model/tokenizer while CPU work runs in a background thread. `FakeEmbeddings` supplies deterministic test vectors; it does not measure semantic quality. |
| `app/storage/knowledge.py` | Define source versions and passages, including text, reference, page, role, retrieval date, content hash, revision, and embedding version. PostgreSQL uses a 384-dimensional pgvector column; small local/offline stores use JSON vectors. |
| `app/services/knowledge.py` | `capture_source()` saves bounded source text, prepares keyword passages, and queues indexing without calling a model. `capture_page()` handles real browser evidence; `capture_document()` handles extracted files. `index(id)` computes vectors and publishes a whole source version in one transaction. Failures preserve the previous searchable version. `search(query)` returns bounded hybrid matches or a labelled keyword fallback. `sources()` lists paginated metadata; `reindex()` queues an explicit rebuild; `recover()` marks interrupted indexing for inspection. |
| `migrations/versions/v001_connected_service.py` | Freeze the original table list so importing a newer model cannot create it before its required migration. Existing application records remain intact. |
| `migrations/versions/v003_knowledge.py` | Add file locations, source/passage tables, relational indexes, the vector extension, a cosine vector index, and a keyword index. A migration is a recorded, repeatable database change. Supabase supplies pgvector; self-hosted PostgreSQL needs the extension installed. |
| `app/connectors/browser/managed.py` | Save the text of actually read public pages into the knowledge library, including cached pages. Preserve the existing page budgets, public-network restrictions, and retry behavior. |
| `app/connectors/telegram/bot.py` | Await asynchronous file saving so uploading an original does not block the message handler. Existing owner restrictions and attachment-role choices still apply. |
| `app/domain/conversation.py`, `app/llm/tools.py` | Add the `search_saved(query)` action and strict function schema. Advertise it only when enabled; reject unavailable tools and invalid arguments. Saved results keep their native function-call identifiers through the existing replay mechanism. |
| `app/agent/prompts/conversation.py` | Explain when to search older knowledge, how to cite it, when current web research is needed, and why owner background must not become evidence about a prospect. |
| `app/services/conversation.py` | Dispatch `search_saved`, record its passages in tool observations, and retain them in checkpoints and history. Preserve an attached file's current role. Exclude background passages and background-derived analysis from prospect-research proposals. Retrieved public URLs can be reread through the restricted browser. |
| `app/services/application.py` | Install knowledge/file services and accept replaceable file/embedding adapters for tests. The same worker handles extraction, indexing, and storage validation. Successful background indexing does not send extra chat notifications. |
| `app/main.py` | Recover interrupted knowledge indexing alongside existing queued work during application startup. |
| `app/services/storage_validation.py` | `validate_storage(service)` creates isolated probe records, a checkpoint, a small original, and a searchable passage. It reports each check and duration, checks private access, removes probes, and reports cleanup failures. Disabled semantic search is marked skipped. Exceptions use fixed safe messages. No Grok/Gmail calls occur. |
| `app/web/routes/control.py` | Add owner-protected original download, source listing, search, reindex, and queued validation endpoints. Search validates trimmed input. Connector status includes the file backend, knowledge/model status, and latest report. Duplicate validation request keys reuse the existing job. |
| `app/web/static/index.html`, `app/web/static/app.js` | Add the Saved knowledge view, search results with cited text, source dates/status, reindex controls, and original downloads. Connections shows storage validation and per-check outcomes. External text uses safe DOM text nodes. Search input is retained during refresh. |
| `pyproject.toml`, `Dockerfile` | Add the optional `semantic` installation extra, include the retrieval fixture in packages, and install the semantic extra in the server image. Model artifacts remain in persistent `.data/models`, outside Git. |
| `evals/retrieval.py`, `evals/retrieval_cases.json` | Measure the actual local model on seven questions over twelve English passages. Compare hybrid and keyword-only ranking; report recall among the first five results and mean reciprocal rank. The latter rewards finding the expected passage nearer the top. This evaluates retrieval, not generated-answer accuracy. |
| `tests/test_knowledge_storage.py` | Check secret handling, private bucket creation, uncertain uploads, checksum conflicts, cloud-like originals across restarts, indexing publication/failures, keyword fallback, cross-conversation search, native tool restrictions, dashboard authentication, validation cleanup, backup/cursor preservation, real pgvector persistence, and stopped-search continuation without a repeated query. |
| `tests/test_server_recovery.py` | Continue checking that migrations preserve existing contacts and repeat safely; update the expected latest migration revision. |
| `README.md`, `docs/SETUP.md`, `docs/SUPABASE.md`, `docs/API_GUIDE.md`, `docs/MODELS_AND_TOOLS.md` | Explain the working database/file/search setup, private key roles, new endpoints and tools, original downloads, validation, and the difference between saved knowledge and task checkpoints. |
| `docs/assets/workflow.mmd`, `docs/assets/workflow.svg` | Update the editable diagram and rendered README image with saved-knowledge search, local embeddings, and private originals. |
| `THIRD_PARTY_NOTICES.md` | Attribute the optional MIT-licensed BGE embedding model and explain that its downloaded files are outside Git. |
| `docs/VALIDATION.md` | Record the automated, retrieval-quality, browser, and cloud-connection evidence separately. |

### What is verified and what still needs your account

The full **494-test suite passed**, including real local PostgreSQL/pgvector, Chromium, and OCR checks. These include closing/reopening a PostgreSQL-backed stopped conversation and continuing with saved passages and budgets, without another embedding query. Confirmed Gmail duplicate protection remains covered by the retained tests.

The real local embedding evaluation retrieved the expected passage among the first five results for **7/7 questions**, compared with **2/7** for keyword-only retrieval on this small fixture. Hybrid mean reciprocal rank was **0.929**. These are small-fixture retrieval results, not a production accuracy claim. All four simulated outreach evaluations also passed; these use scripted model responses and remain separate from this real-embedding check.

A real Chromium walkthrough signed in, uploaded a fictional text file, waited for indexing, searched the library, inspected its cited passage, ran storage validation, and downloaded the unchanged original. It used isolated local data and fake embedding/external services. The rendered dashboard and updated flowchart were inspected. Package dependency, JavaScript syntax, and Git whitespace checks passed.

Cloud provisioning and live Supabase storage verification require the owner's three local credentials. Live Telegram/Grok/Gmail checks still require their configured account access. No paid model request or real email is needed for the automated suite.
