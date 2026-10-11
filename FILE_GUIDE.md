# File guide

Use this page to find the code you need. Open a folder below for file-by-file explanations; the full build log lives in [implementation history](docs/IMPLEMENTATION_HISTORY.md).

## Start here

| File | Main job | Input → output |
|---|---|---|
| [app/main.py](app/main.py) | Starts the service and background worker. | Configuration → running app. |
| [app/services/conversation.py](app/services/conversation.py) | Saves a message and runs the conversation. | Your message → answer or requested work. |
| [app/agent/conversation.py](app/agent/conversation.py) | Chooses, runs, and records conversation steps. | Message + evidence → tool result or reply. |
| [app/agent/graph.py](app/agent/graph.py) | Connects the outreach steps with LangGraph. | Saved state → research, reviewed drafts, outcomes. |
| [app/llm/xai_routing.py](app/llm/xai_routing.py) | Selects the model for each task. | Task type → 4.3, 4.20, or Multi-Agent. |
| [app/llm/tools.py](app/llm/tools.py) | Defines allowed reading tools and validates requests. | Function request → checked action. |
| [app/services/draft_edits.py](app/services/draft_edits.py) | Prepares and applies approved edits. | Existing draft + instructions + approval → same draft updated. |
| [app/storage/control.py](app/storage/control.py) | Saves jobs, conversations, and decisions. | Service actions → durable records. |

**State** is the information needed to continue: your goal, collected evidence, draft, current step, and pending choices. A **checkpoint** saves a workflow's progress. SQLite is the default; configured Supabase stores records and checkpoints in one PostgreSQL database.

## Trace one request

`Telegram → ConversationService.queue() → worker → LangGraph → tools/models → saved result`

Research returns findings. A requested email goes through writing and review. An existing-draft edit uses `DraftEdits.read()` → `prepare()` → your decision → `apply()`. Sending stays manual in Gmail. See the [visual model and email guide](docs/MODELS_AND_TOOLS.md).

## Explore a folder

<details>
<summary>Application entry and configuration</summary>

| File | Purpose, main inputs, and outputs |
|---|---|
| `app/main.py` | `main()` explicitly loads the project’s `.env`, reads startup options, and starts Uvicorn, the web server. `create_app()` assembles routes, authentication, the job worker, and Telegram tasks. Startup applies migrations and recovers interrupted jobs; shutdown lets bounded external actions record results. `/health` reports whether background tasks are still alive. |
| `app/settings.py` | `Settings.from_env()` converts environment values into checked settings. It accepts `xai`, `groq`, or `openai` and defines database, owner, connector, and operating-limit configuration. The template selects xAI; an absent provider setting retains Groq for older installations. It does not contact providers. Secret fields are omitted from the settings object's printed representation. |
| `app/demo.py` | `build_demo_manager()` supplies fake model, search, browser, and Gmail clients to the real workflow. `DemoModelClient` produces fictional records by the requested record type, including a clearly labeled simulated chat reply. `demo_request()` provides a sample request for tests. Start the demo with `python -m app.main --demo`. |
| `pyproject.toml` | Lists Python requirements, dependencies, optional test/Postgres packages, the `outreach-server` command, packaged dashboard assets, migrations, and pytest settings. |
| `.env.example` | Lists configuration names without real secrets. Selects xAI and separate instruction, reasoning, and research models. See [model settings](docs/MODELS_AND_TOOLS.md#model-settings) for their names and [setup](docs/SETUP.md) for alternatives. |
| `.env` (local only) | Stores your real keys and local settings. Startup loads it automatically. Keep each setting once, because a later empty assignment can override a saved key. This file stays outside Git. |
| `.gitignore` | Keeps credentials, databases, environments, and generated outputs out of Git. Root `AGENTS.md` and `plan.md` are also local-only. |
| `AGENTS.md` (local only) | Instructions for coding assistants working in this checkout, including documentation and verification expectations. It is ignored by Git and is not included in fresh clones. |

Every `__init__.py` marks its directory as an importable Python package. These files do not start the service or call external providers.

</details>

<details>
<summary>Conversation, file reading, and saved search</summary>

| File | Main function and input → output |
|---|---|
| `app/agent/conversation.py` | `build_conversation_graph()` connects understanding, tool selection, reading, and answering. A message and its saved observations → a reply or requested work. |
| `app/services/conversation.py` | `queue()` saves a message; `execute()` runs it; `read_tool()` handles allowed reads. User message → saved job → tool results and response. |
| `app/agent/prompts/conversation.py` | Instructions for friendly conversation and task selection. The current message defines the task; old email discussion does not override fresh research. |
| `app/services/tasks.py` | `TaskControls.stop()` and `continue_task()` select and pause/resume saved work. A task choice → the same task continued with its evidence and limits. |
| `app/services/documents.py` | `save_async()` records an uploaded file; `extract()` reads it in a worker. Upload → saved original, extracted text, and reading status. |
| `app/connectors/documents/extractor.py`, `worker.py` | `extract()` reads supported formats and uses OCR for printed image text. A bounded file → text/pages or a clear extraction error. |
| `app/agent/nodes/documents.py` | `prepare_documents()` turns attached text into bounded background or research evidence for the outreach workflow. |
| `app/services/knowledge.py` | `capture_document()` and `capture_page()` save evidence; `index()` prepares it for search; `search()` returns matching passages with sources. |
| `app/storage/files.py`, `documents.py`, `knowledge.py` | Store file originals, extraction records, and searchable passages. Originals use local files or a private Supabase bucket; records use the configured database. |
| `app/llm/embeddings.py` | `LocalEmbeddings.passages()` and `query()` turn text into numeric vectors for similarity search. The model runs locally when this optional feature is enabled. |

</details>

<details>
<summary>Agent core</summary>

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
| `direct.py` | `prepare_direct()` builds the email context for known recipients. `direct_brief()` keeps these explicitly requested drafts on the writing path without prospect discovery. |
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

</details>

<details>
<summary>Shared data and model providers</summary>

| File | Purpose, inputs, and outputs |
|---|---|
| `app/domain/schemas.py` | Pydantic records for a basic goal request, prospects, qualifications, strategies, drafts, and reviews. Pydantic checks types and required fields before the data moves on. |
| `app/domain/workflow.py` | Adds `WorkflowRequest`, `WorkflowState`, sender/recipient records, approval requests/decisions, reply records, outcomes, and memory facts. A request includes research choices and Gmail action; a state adds results, account identity, versions, and progress. Goals remain trimmed and limited to 2,000 characters. |
| `app/domain/browser.py` | `PageEvidence` stores a page URL, title, retrieval time, bounded text, links, explicitly found email addresses, and any read error. |
| `app/llm/client.py` | Defines the common structured-model interface, validation/error helpers, OpenAI adapter, and `FakeModelClient`. `generate_structured()` returns a validated record. `ModelProviderError` takes a provider, known reason, and optional HTTP status; its `public_message` returns an application-written explanation safe to show the owner. |
| `app/llm/groq_client.py` | Sends structured requests to Groq, checks returned JSON, and captures reported token usage. `_request_failure()` translates an HTTP response into a safe failure reason, including organization/project model blocks. Raw provider messages and unknown error codes are not saved or displayed. |
| `app/llm/xai_client.py` | `XAIModelClient.from_env()` reads the xAI key, model, and reasoning choice. `generate_structured()` takes instructions, input text, and a Pydantic record type; makes one xAI Responses request; then returns a locally checked record, such as a qualification score. It bounds visible output, requests `store=false`, and captures token counts. Incomplete output, refusals, or invalid records stop the call. `_request_failure()` returns fixed error text without copying private provider content. `aclose()` closes the connection it owns. |
| `app/llm/xai_routing.py` | `role_for()` assigns a task to instruction, reasoning, or research. `XAITaskRouter.generate_structured()` calls that role's configured model and returns a checked result with usage. |
| `app/llm/tools.py` | `tool_definitions()` lists available reading actions. `checked_call()` validates a requested tool and arguments; `function_history()` pairs saved calls with their results. |
| `app/llm/router.py` | Optional routing helpers retained for measured experiments. Normal xAI requests use `xai_routing.py`; other configured providers keep their own adapter. There is no automatic cheaper-model fallback. |

</details>

<details>
<summary>Connectors</summary>

A **connector** is an adapter between our application and an external service. Fake adapters implement the same operations using local examples, which lets tests exercise real workflow logic without keys or network calls.

| File | Purpose and main operations |
|---|---|
| `app/connectors/search.py` | `PublicSearchTool.search(query)` finds public titles, URLs, and snippets through DuckDuckGo without a key. Runtime selects `BraveSearchTool` instead when a Brave key is present. Results are bounded; the browser reads their page contents. `FakeSearchTool` supplies test examples. |
| `app/connectors/telegram/client.py` | `TelegramClient.call()` sends Bot API requests, bounds timeouts, and sanitizes errors. `RateLimited` carries a retry delay. `FakeTelegram` records calls without contacting Telegram. |
| `app/connectors/telegram/bot.py` | `TelegramBot` sends ordinary text/file captions to the saved conversation queue. `/guided` retains the optional form. It creates review/recipient controls and translates commands into shared-service calls. `poll()` saves owner-only private updates before advancing Telegram’s offset. `process_one()` handles saved updates. `deliver_one()` sends durable outbox messages and avoids blindly repeating an uncertain delivery. Buttons reference saved current versions. |
| `app/connectors/gmail/client.py` | `GmailClient` searches/reads threads and drafts, creates requested drafts, and updates existing drafts at the same ID after the service checks approval. `encode_message()` creates checked email data; `contact_messages()` extracts conversation text for an exact address. `FakeGmailClient` records simulated operations. The connected adapter blocks agent sending. |
| `app/connectors/gmail/drafts.py` | `snapshot()` reads a bounded plain-text draft. `updated_raw()` builds its approved replacement while preserving recipients, attachments, and thread information. |
| `app/connectors/gmail/oauth.py` | `GmailAccount.connect_url()` starts Google sign-in; `complete()` verifies the owner session and granted permissions, then saves the verified address and encrypted tokens. `CredentialVault` encrypts/decrypts secret records. `token()` renews an expired token. `disconnect()` removes local credentials and attempts Google revocation. `BoundGmail` holds the account lock through each request so an approval cannot switch accounts mid-action. |
| `app/connectors/browser/client.py` | `BrowserClient.read(url)` returns `PageEvidence` using a fresh sandboxed Chromium session. `extract_emails()` accepts addresses actually present in visible text or a single-recipient contact link. `FakeBrowser` returns local evidence. Browser sessions have no personal login cookies, and submissions/downloads/WebSockets are blocked. |
| `app/connectors/browser/network.py` | `parse_public_url()` checks HTTP/HTTPS URLs and ports. `public_address()` rejects private, local, reserved, or mixed public/private DNS answers. `PublicProxy` connects to the validated IP, covering redirects and subrequests too. This prevents a second DNS lookup from changing the destination to a private service. |
| `app/connectors/browser/managed.py` | `ManagedBrowser.read()` reserves a page attempt in the database before browsing, saves evidence, and reuses saved evidence on retries. Restarts do not reset limits. |

</details>

<details>
<summary>Services and persistence</summary>

| File | Purpose and main operations |
|---|---|
| `app/services/application.py` | `AgentService` is the shared entry point for both interfaces. `start()` queues outreach; `stage_decision()` saves one choice; `submit_choices()` queues a complete batch; `select_recipients()`, `retry()`, and `cancel()` control saved work. `execute_one()` also runs chat jobs through `ConversationService`. Chat retries stay in the conversation graph. `check_replies()` processes bounded new inbound messages. `overview()`, `list_runs()`, and `details()` return dashboard data and paginated events. |
| `app/services/draft_edits.py` | `DraftEdits.read()` fetches an existing message; `prepare()` saves proposed changes; `decide()` records your choice; `apply()` updates the same Gmail draft after approval. A changed account/message or uncertain write blocks repetition. |
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

</details>

<details>
<summary>Dashboard and deployment files</summary>

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

</details>

<details>
<summary>Tests and evaluations</summary>

The validation record lists completed automated suites, including optional Chromium and real image/scanned-PDF OCR fixtures. All four simulated evaluation scenarios pass. Packaging and restart checks are recorded in [validation](docs/VALIDATION.md).

**Tests** check behavior with known inputs. **Evaluations** score outreach results against small reference cases. A successful simulation confirms the workflow and scoring logic; it does not prove a real model’s research accuracy or writing quality.

| File | What it checks in everyday language |
|---|---|
| `tests/conftest.py` | Provides fresh fictional records and isolated databases/settings. Removes exported xAI, Groq, OpenAI, and application settings during each test so local credentials cannot accidentally turn tests into live calls. |
| `tests/test_schemas.py`, `test_state.py` | Input types, goal trimming/length, strict records, JSON conversion, and independent run collections. |
| `tests/test_client.py`, `test_groq_client.py` | Structured response validation, safe provider failure explanations, malformed error bodies, token information, and Groq configuration. |
| `tests/test_xai_client.py` | Uses simulated HTTP responses to check xAI request bounds, JSON validation, token counts, key selection, and safe errors. Runs a Telegram greeting and a six-call outreach workflow through the real adapter; checks duplicate messages, approval without extra calls, dashboard key status, and bounded retries. No paid model requests are made. |
| `tests/test_model_routing.py`, `test_research_routing.py` | Check model roles, valid tool arguments, required first reads, and fresh research after an email conversation. All provider responses are simulated. |
| `tests/test_gmail_draft_edits.py` | Check edit previews, approval/rejection, same-ID replacement, stale decisions, and preserved message content. Gmail is simulated. |
| `tests/test_documents.py`, `test_supabase_storage.py` | Check file extraction, private storage, and saved-work recovery. Optional PostgreSQL checks use a temporary local database. |
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

</details>

## What was built when

| Phases | Delivered | Details |
|---|---|---|
| 1–30 | Foundation, structured records, outreach steps, memory, evaluations. | [Original phase history](docs/PHASE_HISTORY.md) |
| 31–36 | Shared service, Telegram, Gmail, browser, dashboard, saved jobs. | [Implementation record](docs/IMPLEMENTATION_HISTORY.md#phase-history-what-changed-when) |
| 37–42 | File reading, normal conversation, providers, draft-only Gmail. | [File reading onward](docs/IMPLEMENTATION_HISTORY.md#phase-37--read-files-and-use-them-in-research) |
| 43–45 | Model roles, native tools, continuation, private files, semantic search. | [Model roles onward](docs/IMPLEMENTATION_HISTORY.md#phase-43--model-roles-and-native-tool-calls) |
| 46–48 | Responsive Telegram, readable progress, direct drafts, immediate starts. | [Telegram improvements](docs/IMPLEMENTATION_HISTORY.md#phase-46--telegram-response-speed-and-visible-task-progress) |
| 49 | Keyless search, complete emails, approved same-draft edits. | [Phase 49](docs/IMPLEMENTATION_HISTORY.md#phase-49--reliable-tools-complete-emails-and-approved-gmail-edits) |
| 50 | Smaller visual guides and easier documentation navigation. | Changes below. |

<details>
<summary>Phase 50 — Visual documentation</summary>

| Files | Purpose and change |
|---|---|
| `docs/assets/workflow.mmd`, `workflow.svg` | Short request overview. Mermaid source → rendered SVG image. |
| `docs/assets/email-flow.mmd`, `email-flow.svg` | New draft and existing-draft edit paths, including owner approval and manual sending. |
| `docs/assets/model-routing.mmd`, `model-routing.svg` | Three model roles and application-controlled tool execution. |
| `README.md` | Project introduction, four usage examples, quick demo, and links. |
| `docs/SETUP.md` | Essential setup steps, optional connection details, and a short acceptance check. |
| `docs/MODELS_AND_TOOLS.md` | Visual model map, tool reference, email flow, and saved-work controls. |
| `FILE_GUIDE.md` | Short code map, expandable folder references, and linked phase summary. |
| `docs/IMPLEMENTATION_HISTORY.md` | Preserves the previous detailed explanations and all phase records through 49. |
| `docs/TROUBLESHOOTING.md` | Moves provider/account, file-reading, and restart problems out of the setup path. |
| `docs/VALIDATION.md`, `docs/VALIDATION_HISTORY.md` | Current verification summary, with the full previous log available separately. |
| `docs/SUPABASE.md` | Corrects its email-use paragraph to match immediate starts and approved existing-draft edits. Storage setup is unchanged. |

</details>

This phase changes documentation; the application's behavior stays the same. See [validation](docs/VALIDATION.md) for link, diagram, and display checks.
