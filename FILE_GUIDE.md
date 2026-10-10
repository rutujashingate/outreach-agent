# File guide

This guide explains the working application in plain language. The [setup guide](docs/SETUP.md) explains how to run it. The [API guide](docs/API_GUIDE.md) describes requests used by the dashboard. Earlier work is preserved in [phase history](docs/PHASE_HISTORY.md) and the [previous file guide](docs/FILE_GUIDE_HISTORY.md).

## Follow one request

1. You talk normally to the Telegram bot. `ConversationService.queue()` saves your message, and a LangGraph conversation loop answers, reads files/public pages, searches when available, or proposes outreach. It remembers the last six exchanges across restarts. `/new` optionally resets this context; `/guided` opens the old step-by-step questions. Dashboard requests still enter outreach directly.
2. If you request outreach, check the proposed request and press **Start outreach**. `AgentService.start()` validates its choices, saves a run and a job, and returns their identifiers immediately. A **run** holds results; a **job** is one queued piece of work. Uploaded-file jobs extract text locally before the run uses it. Ordinary conversation ends with a reply and does not require an outreach run.
3. One worker takes the job. `RunManager` opens the saved **LangGraph workflow**, an ordered set of steps with explicit choices about where to go next.
4. The agent loads ready files, interprets the goal using relevant excerpts, researches uploaded/public evidence, qualifies prospects, resolves addresses, checks relationship history and contact rules, then writes and reviews messages.
5. Missing or ambiguous addresses pause the run for your selection. Reviewed drafts pause for your decisions. The database saves both pauses so restarting does not lose them.
6. You select approve, reject, or edit for **every** pending prospect, then submit the batch. Telegram and the dashboard share these choices. An edit goes through review and needs a fresh approval.
7. The worker verifies the current account, recipient, exact message, version, requested action, and contact rules. It records the Gmail action before and after calling Gmail. An uncertain result stays blocked for inspection.
8. The dashboard displays the same saved run, sources, outcomes, events, and usage. No second research run is needed to switch interfaces.

For example, “Find professors studying AI observability” can become a sourced professor record and a reviewed email. Approval in draft mode creates a Gmail draft; it does not send it. The included demo uses a fictional university and simulated services.

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

## Application entry and configuration

| File | Purpose, main inputs, and outputs |
|---|---|
| `app/main.py` | `main()` explicitly loads the project’s `.env`, reads startup options, and starts Uvicorn, the web server. `create_app()` assembles routes, authentication, the job worker, and Telegram tasks. Startup applies migrations and recovers interrupted jobs; shutdown lets bounded external actions record results. `/health` reports whether background tasks are still alive. |
| `app/settings.py` | `Settings.from_env()` converts environment values into checked settings. It selects Groq by default and defines database, owner, connector, and operating-limit configuration. It does not contact providers. Secret fields are omitted from the settings object’s printed representation. |
| `app/demo.py` | `build_demo_manager()` supplies fake model, search, browser, and Gmail clients to the real workflow. `DemoModelClient` produces fictional records by the requested record type, including a clearly labeled simulated chat reply. `demo_request()` provides a sample request for tests. Start the demo with `python -m app.main --demo`. |
| `pyproject.toml` | Lists Python requirements, dependencies, optional test/Postgres packages, the `outreach-server` command, packaged dashboard assets, migrations, and pytest settings. |
| `.env.example` | Documents configuration names without real secrets. Copy missing settings into your local `.env`; keep existing credentials. Service startup loads it automatically. |
| `.gitignore` | Keeps credentials, databases, environments, and build outputs out of Git. |

Every `__init__.py` marks its directory as an importable Python package. These files do not start the service or call external providers.

## Agent core

A **node** is a small workflow step. It receives the current state and the run’s services, then returns a dictionary containing only the fields it changed. LangGraph combines those changes with the saved state.

| File | Purpose and main functions |
|---|---|
| `app/agent/graph.py` | `build_full_graph(checkpointer)` returns the main executable workflow. `build_research_graph()` groups interpretation, research, and qualification; `build_outreach_graph()` groups strategy, writing, and review. `observed()` wraps steps with cancellation checks, timings, events, and current-step reporting. |
| `app/agent/state.py` | Defines `OutreachState`: the goal and separate collections for prospects, qualifications, strategies, drafts, reviews, and progress. The complete state extends it in `domain/workflow.py`. New runs never share mutable collections. |
| `app/agent/context.py` | `WorkflowContext` passes services to nodes. `ManagedModelClient` and `ManagedSearchTool` reserve persistent budgets before calls, enforce timeouts, and record usage. This keeps controls outside model prompts. |
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
| `approval.py` | `prepare_approval()` builds the exact review cards and message versions. `human_approval()` pauses and applies a complete decision batch. `validate_decisions()` rejects missing, duplicate, or stale decisions. Edits require review and another approval. |
| `external.py` | `external_node()` rechecks approval, account identity, contact policy, and the durable action ledger before draft/send calls. `finish_node()` saves outcomes and interaction history. An uncertain write is recorded without automatically repeating it. |
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
| `app/llm/client.py` | Defines the common structured-model interface, validation/error helpers, OpenAI adapter, and `FakeModelClient`. `generate_structured()` returns a validated record rather than unchecked model text. |
| `app/llm/groq_client.py` | Sends structured requests to Groq, checks returned JSON, and captures reported token usage. It implements the same interface as the other model adapters. |
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
| `app/services/runs.py` | `RunManager` connects saved runs to LangGraph. `execute_new()`, `resume()`, `select_recipients()`, and `retry()` execute or continue a saved run. `_execute()` owns leases, checkpoints, failures, and cancellation. `context()` supplies per-run adapters, including an account-bound Gmail client. Model clients are opened only when needed. |
| `app/services/runtime.py` | `open_runtime()` opens the database, checkpoint connection, HTTP clients, and configured connectors, then closes them together. Demo mode injects fake services. |
| `app/services/auth.py` | `OwnerAuth.login()` verifies the configured password and creates an opaque session. Password verification uses Argon2 hashing. `require_owner()` checks either an API key or owner session; browser writes also need a CSRF token, which prevents another site from silently submitting owner actions. Browser sessions expire on restart; saved approvals remain. |
| `app/services/cancellation.py` | `check_cancelled()` reads the saved stop request and raises `RunCancelled` at a safe boundary. A Gmail action already underway finishes recording its result. |
| `app/services/instance.py` | `instance_lock()` locks the data directory while the service runs. A second local process using that directory fails clearly instead of starting a second worker/poller. |
| `app/services/limits.py` | `Limits` defines page/call counts, timeouts, concurrency, contact windows, revision limits, and estimated spending. Ordinary chat has a smaller default allowance: six model attempts and five tool selections per message, also constrained by the overall limits. Estimated cost is a configured per-call reservation, not a provider invoice. |
| `app/storage/models.py` | Defines tables for contacts, memory, interactions, runs, traces, action locks, and the external-action ledger. A ledger is the durable record used to recognize an already attempted action. |
| `app/storage/control.py` | Defines job, run-metadata, key/value, Telegram inbox, and outbox tables. `ControlStore.enqueue()` saves a run and initial job together, labeling chat separately from outreach and recording its latest turn in the same transaction. `claim()` honors queue pause. `recover()` marks interrupted work. Other methods persist conversations, approval selections, update offsets, page counts, and encrypted connector records. A repeated request key returns its original job. |
| `app/storage/database.py` | `create_database()` opens SQLite by default and applies application migrations. Existing relationships are retained. |
| `app/storage/repository.py` | Reads/writes relationship facts, outcomes, runs, budgets, leases, and action claims. It is reused by the workflow, reply processing, and shared service. |
| `app/storage/checkpoints.py` | `open_checkpointer()` opens LangGraph’s progress store. SQLite is the service default. Its serializer recognizes relocated domain records and earlier record names. Memory and optional Postgres adapters remain for tests/earlier integrations. |
| `app/storage/events.py` | `trace()` writes timestamped events and updates the currently running node. `events()` returns a run’s ordered trace. Events record useful metadata, not credentials or full model prompts. |
| `migrations/env.py` | Connects Alembic, the migration runner, to the application’s existing database connection. |
| `migrations/versions/v001_connected_service.py` | The first versioned migration adopts earlier tables without discarding data, adds service tables, and backfills metadata for existing runs. It deliberately has no destructive automatic downgrade. |

The normal local installation uses **SQLite only**, with two files: `relationships.sqlite3` stores application records and `checkpoints.sqlite3` stores LangGraph progress. It does not require PostgreSQL. Both live under `OUTREACH_DATA_DIR`; the demo uses its `demo/` subdirectory. Credentials are encrypted in the application database; their encryption key stays in your environment.

## Dashboard and deployment files

| File | Purpose |
|---|---|
| `app/web/routes/control.py` | Authenticated `/api` routes validate incoming data and call `AgentService`. Run/reply/resume work returns HTTP 202 with a job identifier. Connector routes handle Google sign-in and status. The demo-only Telegram endpoint exercises the bot adapter locally. |
| `app/web/static/index.html` | The dashboard’s page structure: login, navigation, content area, and run/edit forms. |
| `app/web/static/app.js` | Fetches shared-service data, renders views, stages decisions, and submits controls. The new-run form accepts known addresses; run details retain completed drafts, reviews, decisions, and source retrieval times. Refreshes the visible view every five seconds while leaving active form entry alone. `node()` creates text safely instead of interpreting external content as HTML. Run submission preserves a request key after a lost response. |
| `app/web/static/app.css` | Styles the responsive dashboard, review cards, forms, tables, status badges, and compact logs. |
| `Dockerfile` | Builds the Python service with matching Chromium dependencies and runs it as a non-root user. |
| `compose.yaml` | Starts one container with persistent data, local port binding, health checks, graceful shutdown, and browser sandbox configuration. |
| `.dockerignore` | Excludes local credentials, databases, Git history, and environments from the build context. |
| `docker/seccomp_profile.json` | Upstream Playwright system-call profile allowing Chromium’s sandbox to create user namespaces. |
| `docker/PLAYWRIGHT_LICENSE`, `THIRD_PARTY_NOTICES.md` | Preserve the upstream profile’s Apache 2.0 license and attribution. Our project remains MIT licensed. |
| `README.md` | Short project introduction, working features, diagram, and demo command. |
| `docs/SETUP.md` | Local configuration, Telegram/Google setup, daily operations, and Docker instructions. |
| `docs/API_GUIDE.md` | Current authenticated endpoints and request/response examples. |
| `docs/VALIDATION.md` | Records what was actually tested and the remaining live-environment checks. |
| `docs/assets/workflow.mmd`, `workflow.svg` | Editable Mermaid flowchart and its rendered image. Shows the actual shared request path and approval loop. |
| `plan.md` | The implemented direction, defaults, acceptance criteria, and live validation boundary. |
| `CONTRIBUTING.md`, `LICENSE` | Contributor workflow and MIT licensing terms. Contributors retain their copyright and license contributions under MIT. |

## Tests and evaluations

The completed local suite passes **376 tests**, including optional Chromium and real image/scanned-PDF OCR fixtures. All four simulated evaluation scenarios pass. Packaging and restart checks are recorded in [validation](docs/VALIDATION.md).

**Tests** check behavior with known inputs. **Evaluations** score outreach results against small reference cases. A successful simulation confirms the workflow and scoring logic; it does not prove a real model’s research accuracy or writing quality.

| File | What it checks in everyday language |
|---|---|
| `tests/conftest.py` | Provides fresh fictional records and isolated databases/settings. Real local keys cannot accidentally turn tests into live calls. |
| `tests/test_schemas.py`, `test_state.py` | Input types, goal trimming/length, strict records, JSON conversion, and independent run collections. |
| `tests/test_client.py`, `test_groq_client.py` | Structured response validation, provider failures, token information, and Groq configuration. |
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
| `evals/scoring.py` | `score_run(state, reference)` compares targets, sources, qualification, memory, hooks, writing constraints, reviews, and workflow approval rules. It returns numbers from 0 to 1. |

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
