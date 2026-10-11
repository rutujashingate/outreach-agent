# Local validation

## Immediate starts for clear Telegram requests — October 11, 2026

- Clear instructions to draft now queue the existing workflow directly. The optional confirmation remains when the owner explicitly asks to wait. Research and file-reading requests retain their immediate read-only execution and do not create emails.
- **527 tests passed** with `RUN_POSTGRES_TESTS=1 RUN_BROWSER_TESTS=1 RUN_OCR_TESTS=1 .venv/bin/pytest -o addopts='' -o faulthandler_timeout=30 -q --tb=short`, including real local PostgreSQL/pgvector, Chromium, and OCR checks. The targeted conversation, direct-drafting, continuation, and background-recovery checks passed too.
- Fake Telegram-to-Gmail execution creates one draft from a repeated owner update with no confirmation button and no send call. A new interruption check loses confirmation just after queuing the child run, rebuilds the service, and retries after another chat message; it reuses that run and creates one draft. Explicit wait requests still create no Gmail action before confirmation, repeated clicks start once, and changed requests invalidate stale proposals.
- Existing edit/version checks, contact checks, budgets, uncertain-write handling, and the prohibition on agent sending remain covered by the suite. Older saved proposals keep waiting rather than being silently started during the upgrade.
- Updated setup instructions, the README, and the phase-by-phase file guide. Rendered and visually inspected the revised workflow image.
- Paused the idle queue, gracefully restarted the local service, and restored its earlier unpaused setting. Owner login and health succeeded; the worker, Telegram poller, message handler, and progress display all reported running. Telegram and Gmail stayed connected, with the existing Supabase database retained.

The workflow checks use fake Telegram, models, and Gmail. Actual provider interpretation and a requested draft appearing in the owner's Gmail remain live acceptance checks; diagnostics do not start an extra conversation, paid model call, or email action.

## Friendly Telegram conversation and direct email drafting — October 11, 2026

- The reported test-email request was following company discovery and qualification, so an empty prospect list prevented drafting. Added a direct path for explicitly supplied recipients, joining the existing memory, contact, writing, review, and draft-saving steps. Requests to find new prospects still use research and qualification.
- **526 tests passed** with `RUN_POSTGRES_TESTS=1 RUN_BROWSER_TESTS=1 RUN_OCR_TESTS=1 .venv/bin/pytest -o addopts='' -o faulthandler_timeout=30 -q --tb=short`. This includes real local PostgreSQL/pgvector, Chromium, and OCR. Fifteen new direct-drafting scenarios use fake external services and cover ordinary requests, opt-outs, active conversations, missing recipients, limits, review failures, duplicate clicks, saved continuation, remembered edits, and retry buttons.
- Fake Telegram-to-Gmail checks produce one confirmed draft from repeated confirmation clicks, show its preview, and make no send call. A restart scenario reuses the saved writing result and completes review without repeating generation or saving twice. With no memory extraction or revisions, the direct workflow makes two model calls: writing and review. Conversation interpretation is separate.
- Progress checks verify only **Queued…**, **Researching…**, and **Typing…**, with native typing and cleanup after completion. Replies omit timers and internal IDs. File and saved-library citations display source names and page numbers while retaining exact internal references in the evidence.
- All four offline evaluation examples passed their existing scoring checks. These simulations verify workflow/scoring behavior, not real model quality. The revised architecture diagram was rendered and visually inspected.
- Paused the idle queue and gracefully restarted the local service with the fix. Owner login and health returned successfully; Telegram and Gmail remained connected, Supabase remained the active database, and the queue returned to its previous unpaused setting. Credentials and stored requests were retained.

Actual provider wording and a newly requested draft appearing in the owner's Gmail remain live acceptance checks. Diagnostics do not initiate paid model generation, an extra Telegram conversation, or a real Gmail draft/email. The agent continues to save only requested drafts; the owner reviews and clicks Send in Gmail.

## Telegram background recovery — October 11, 2026

- The local process was alive, but `/health` returned HTTP 503 and `degraded`. Read-only Telegram checks confirmed the token was valid, no webhook was configured, and one update was waiting. No new chat job had been received. The old process also reported a closed database connection while shutting down; it had not recorded the original task exit, so that exception could not be identified retrospectively.
- Added recovery at the background-loop boundary for temporary database connection failures and connection-pool timeouts. The wait starts at five seconds and increases to at most 30 seconds. Telegram startup/network failures can recover too. Unexpected task exits now record a component name and error class, without private exception text. Health exposes component statuses and reports a stopped or retrying component as degraded.
- **511 tests passed** with `RUN_POSTGRES_TESTS=1 RUN_BROWSER_TESTS=1 RUN_OCR_TESTS=1 .venv/bin/pytest -o addopts='' -o faulthandler_timeout=30 -q --tb=short`. Seven new checks verify worker recovery, persisted-update deduplication after a lost database confirmation, conversation-save recovery without repeating a completed command, suppression of uncertain Telegram resends, temporary Telegram startup recovery, safe task-exit reporting, and shutdown during backoff. The suite includes real local PostgreSQL/pgvector, Chromium, and OCR; fake external services handle these recovery scenarios.
- Paused the idle queue, stopped the old process, and restarted with the fix. Restored the prior queue setting. Health subsequently returned HTTP 200 with the worker, Telegram poller, handler, and progress display all `running`. Telegram and Gmail remained connected.
- The service naturally processed the owner's already-waiting message: completed chats increased from three to four, all five saved inbox updates were processed, and all five durable final-message records were delivered. No additional test chat, Gmail draft, or email was initiated by diagnostics. Existing cloud data, credentials, and connected accounts were retained.

The recovery loop claims queued work rather than replaying an interrupted job. Existing explicit-retry and uncertain-external-write safeguards remain in place. A different code error still stops its component and is reported; it is not silently retried forever.

## Telegram speed and task progress — October 10, 2026

- Inspected the existing hosted records without exposing message contents: three recent chats took approximately **24, 30, and 42 seconds** from job creation to completion; their individual model steps took approximately **3, 3, and 5 seconds**. Code inspection found repeated synchronous cloud reads on the shared network loop, alongside unnecessary separate value/control queries.
- **504 tests passed** with `RUN_POSTGRES_TESTS=1 RUN_BROWSER_TESTS=1 RUN_OCR_TESTS=1 .venv/bin/pytest -o addopts='' -o faulthandler_timeout=30 -q --tb=short`. This includes real local PostgreSQL/pgvector, Chromium, and OCR checks. New progress checks use fake Telegram/model services; no provider credentials are needed.
- New checks cover one edited status message, fixed stage labels, typing renewal, elapsed-time updates, rate-limit waits, suppression after uncertain delivery, no private content in statuses, and a final answer surviving progress-delivery failure. Deliberately held-open database/model calls do not stop progress delivery. Twenty parallel database reservations still accept exactly ten calls at a ten-call budget, with the correct saved cost. Existing stop/continue and duplicate-draft protections passed.
- A single local comparison injected **25 ms per SQL statement**, used a fake model and an in-memory LangGraph checkpointer, and compared the previous committed code with this change. SQL statements fell from **75 to 55**; worker time fell from **1.827 to 1.343 seconds**; the longest event-loop heartbeat gap fell from **0.568 to 0.015 seconds**. Both used one model call. This measures application overhead under artificial database latency; it is not a live Telegram or model speed guarantee and does not include hosted checkpoint/network latency.
- Real Supabase atomic value writes, batched reads, and fresh stop-flag reads passed, and their temporary records were removed. Package dependencies, Python compilation, dashboard JavaScript syntax, Git whitespace, and updated documentation links passed.
- The local service restarted with retained cloud data and queue settings. Health returned `ok`; Telegram and Gmail both reported connected, and the previously passed storage report remained present. Google app credentials and Gmail account authorization are explained separately in setup; Telegram and the dashboard share one connected account.

No paid model generation, unsolicited Telegram test message, Gmail draft, or email was requested by these diagnostics. Test the visible statuses with your next ordinary Telegram message or supplied-page request. Research/model duration still depends on the requested work and external services. Progress messages are temporary display data; saved task state and final replies remain durable.

## Password rotation recheck — October 10, 2026

- After the owner rotated the database password, a new direct PostgreSQL connection succeeded. Corrected URL encoding in the ignored local `.env`, then gracefully restarted the service so it used the new value. Existing cloud records and queued-work settings were preserved.
- Owner login and `/health` succeeded. A fresh dashboard-backend validation passed all six real checks: database, checkpoint, files, private access, semantic search, and cleanup. The queue was restored to its previous unpaused setting.
- Telegram reported connected. The restricted Chromium browser read a public page and extracted its title and text. OCR was available. Brave search remained unconfigured, so independent website discovery still needs its key.
- Read-only xAI checks returned HTTP 200, reported no blocked/disabled key or blocked team, and listed all three configured model IDs. No paid generation was requested; these checks do not establish live response quality or successful generation.
- Gmail remained disconnected in the new cloud store. Reconnecting it and creating an explicitly requested test draft remain owner checks. No Telegram message, Gmail draft, or email was sent by these diagnostics.
- Added a practical [connected-application checklist](SETUP.md#check-your-connected-application). This follow-up changed documentation and local ignored configuration only. Git whitespace and documentation-link checks passed; the earlier 497-test code result below was not rerun for prose changes.

## Hosted Supabase connection and dashboard responsiveness — October 10, 2026

- The owner supplied credentials privately. Corrected the password's URL encoding without changing the database password, stopped the idle local service, backed up its SQLite files under `.data/backups`, and enabled Supabase originals and semantic search. The three failed local test jobs remain in the archive; old runs and Google tokens were not imported.
- Hosted setup created the private `outreach` schema, application/checkpoint tables, pgvector indexes, and private `outreach-documents` bucket. Database, checkpoint, original-file, private-access, semantic-retrieval, and cleanup checks all passed against the actual project using the real local embedding model.
- Read-only inspection found **20 application/checkpoint tables**, all with row-level security enabled, pgvector in `extensions`, both knowledge-search indexes, and no remaining validation sources, checkpoints, or temporary database records.
- One dashboard-triggered check reported a file round-trip failure. An isolated write/read/delete and a repeated worker validation passed. Synchronous dashboard/database reads and browser-session lookup now run in background threads so cloud latency cannot block the main request loop. The original failure was reported rather than silently treated as a pass.
- Demo mode now clears cloud database/file credentials and uses local originals and checkpoints. This prevents a demo launched beside a cloud-configured `.env` from uploading fictional files to the real bucket.
- **497 tests passed** with `RUN_POSTGRES_TESTS=1 RUN_BROWSER_TESTS=1 RUN_OCR_TESTS=1 .venv/bin/pytest -o addopts='' -q --tb=short`. Three new checks cover demo isolation and health requests completing while a dashboard read or session lookup is deliberately paused. Package dependency, JavaScript syntax, and Git whitespace checks passed.
- The service restarted on the hosted database, and its passed validation report survived another restart. Health returned `ok`, Telegram reported connected, and the previous queue setting was restored. No paid model inference or real Gmail draft/email was requested.
- A real Chromium walkthrough signed in to the live dashboard, opened Connections, queued storage validation while the view refreshed, confirmed all six hosted checks passed, and opened Saved knowledge. The final Connections screen was visually inspected. This used the owner's actual Supabase project and real local embeddings; it did not call the language model or Gmail.

**Owner checks remaining:** reconnect Gmail in this fresh cloud store, verify actual xAI model access, and test a requested draft through Telegram. Database connectivity does not establish provider credits or live answer quality. Docker execution and remote hosting remain unverified.

The entries below preserve what was verified before hosted credentials were added.

## Private originals, pgvector retrieval, and storage checks — October 10, 2026

- **494 tests passed** with `RUN_POSTGRES_TESTS=1 RUN_BROWSER_TESTS=1 RUN_OCR_TESTS=1 .venv/bin/pytest -o addopts='' -q --tb=short`. These include real local PostgreSQL/pgvector, Chromium, and OCR checks. Hosted Supabase requests use simulated HTTP responses; no cloud credentials are required for the suite.
- New checks cover private bucket creation, server-key headers, bounded original downloads, upload reconciliation after a lost response, checksum verification, durable extraction/indexing, failed rebuilds retaining previous passages, keyword fallback, owner authentication, and temporary validation-data cleanup. A PostgreSQL conversation checkpoint was closed/reopened and continued with its saved search result and usage, without a second embedding query.
- The actual local BGE embedding model retrieved the expected passage among the first five results for **7/7 questions**, compared with **2/7** for keyword-only retrieval on a 12-source English fixture. Hybrid mean reciprocal rank was **0.929**. This small retrieval fixture does not measure generated-answer accuracy or establish production relevance.
- All four existing simulated outreach evaluations passed. These use scripted model responses and are separate from the real-embedding retrieval evaluation.
- A real Chromium dashboard walkthrough signed in, uploaded a fictional text file, waited for indexing, searched saved knowledge, inspected the cited passage, ran storage validation, and downloaded the unchanged original. It used isolated local storage and fake embeddings/external services. The dashboard and rendered architecture diagram were visually inspected. Package dependencies, JavaScript syntax, and Git whitespace checks passed.
- The local `.env` and shared template were simplified. Existing credential values and custom usage limits were preserved; redundant defaults and empty legacy settings were removed. The three new Supabase credential fields remain blank. Local databases, cached models, backups, and evaluation reports stay outside Git.

**Still to verify:** hosted provisioning, private-bucket access, and hosted checkpoint/retrieval checks after the owner enters the three credentials in [Supabase setup](SUPABASE.md). Existing local records are preserved; switching stores does not import them. The running real service was not restarted, and no paid model request or real Telegram/Gmail message was sent. Live account/model acceptance and Docker execution remain separate checks.

Earlier entries describe the checks and limitations at their respective phases.

## Model roles, tool calls, and task continuation — October 10, 2026

- **470 tests passed** with `RUN_POSTGRES_TESTS=1 RUN_BROWSER_TESTS=1 RUN_OCR_TESTS=1 .venv/bin/pytest -o addopts='' -q --tb=short`. Real local Chromium, OCR, and temporary Postgres checks were enabled; no cloud credentials were required.
- Mocked xAI Responses requests verified the 4.3 → 4.20 tool selection → Multi-Agent analysis → 4.20 answer sequence. A separate outreach scenario verified all six task-to-model routes. Native function names, arguments, capabilities, call/result IDs, and limits were checked. Unsupported tool calls were rejected.
- A real SQLite checkpoint was closed and reopened after a page read and model failure. A plain Telegram **continue** resumed the same goal/run ID with retained evidence, no second browser visit, and the original usage counters. Other checks cover stopped queued work, stop during a read, saved results before a checkpoint, completed-task recovery, ambiguous task selection, retention after many later questions, and a fresh proposal after continuing an older task.
- Continue did not approve a draft or select a missing recipient. Permanent cancellation and exhausted budgets remained enforced. A stopped outreach run resumed without repeating completed model stages and created one fake Gmail draft.
- All four simulated evaluations passed. JavaScript syntax and Git whitespace checks passed. The Mermaid diagram was rendered and visually inspected for the updated README.
- Only non-secret routing fields were changed in local `.env`. Credentials and local databases were preserved. No paid model call or real Telegram/Gmail message was sent; the running real service was not restarted.

**Live checks still needed:** restart the service, verify xAI account access to all three configured models, then test a real conversation and requested draft. Simulated responses test integration behavior, not actual model quality. Multi-agent research analyzes evidence from the application's tools; provider-hosted search is not enabled. The broader validation dashboard has not been added.

## Model routing and tool calls — October 10, 2026

130 focused tests passed across model routing, xAI compatibility, conversation, full outreach, checkpoints/controls, authenticated API, and the shared service. `node --check app/web/static/app.js` passed. New mocked HTTP checks exercised the requested three-model sequence and native function calls through the actual graph; invalid tool requests were rejected. No live provider generation or real Telegram/Gmail message was sent. All model routes still need live account access and a quality check on real inputs. Local `.env` changes were limited to non-secret role settings and preserved existing credentials.

## Supabase state and requested drafts — October 10, 2026

- **443 tests passed** with `RUN_POSTGRES_TESTS=1 RUN_BROWSER_TESTS=1 RUN_OCR_TESTS=1 .venv/bin/python -m pytest -o addopts='' -q --tb=short`. This includes real local Chromium, OCR, and a disposable PostgreSQL 16 cluster. Supabase cloud credentials were not used. A final connector-message wording change also passed the 10 Gmail OAuth tests.
- Real Postgres checks applied migrations in the private `outreach` schema, saved jobs and LangGraph checkpoints, reopened a paused run, and resumed without repeating model work. Another service's database lock was rejected. Row-level security and absence of Data API role access were verified through SQL. A confirmed fake Gmail draft was reused after restart instead of being created again.
- Draft behavior checks cover explicit owner start, no Gmail writes before that start, reviewed draft creation without fabricated human approval, contact opt-outs, failed review, unchanged contact timestamps for unsent drafts, duplicates, uncertain results, cancellation, and notification wording. New API send requests, legacy send runs, old sending flags, and connected Gmail send calls are blocked.
- All four simulated evaluations passed. These verify code and scoring against fixed examples, not live model quality. The evaluation report remains in ignored `.data`.
- A real Chromium dashboard walkthrough signed in, inspected the SQLite storage card, submitted the fictional request through **Start drafting**, and displayed a completed fake Gmail draft with **Open Gmail Drafts** guidance. The send option is absent. The updated Mermaid diagram was rendered and visually inspected. JavaScript syntax and Git whitespace checks passed.
- The normal service was paused while idle, shut down gracefully, and restarted with the updated code. Health returned `ok`, Telegram connected, the selected model remained `xai`, and agent sending reported `false`. Storage remained SQLite with SQLite checkpoints; all three saved failed chat jobs remained. The previous queue state was restored. No model inference or real Gmail action was requested during these checks.

**Still to verify with owner accounts:** create the Supabase project and set its connection URL; verify actual hosted connectivity and reconnect Gmail in that store; resolve the existing xAI account restriction and test a requested draft. SQLite files and credentials are preserved, but no local-to-cloud data migration was performed. Docker dependencies were updated; a container build was not run. Manual Gmail sending is performed by the owner and is not automatically reconciled into the app's historical sent counter.

Earlier sections below are historical records of the behavior and checks at those phases.

## Grok on xAI — October 10, 2026

- **425 tests passed** with `RUN_BROWSER_TESTS=1 RUN_OCR_TESTS=1 .venv/bin/python -m pytest -o addopts='' -q`, including local Chromium/OCR and the existing simulated evaluations. The focused provider, Telegram-conversation, and dashboard suite passed all 102 tests.
- The xAI adapter was exercised through simulated HTTP responses: structured JSON requests, explicit reasoning `none`, bounded visible output, `store=false`, local record validation, reported token counts, incomplete output, refusals, and connection failures.
- A normal fake Telegram greeting reached the real xAI adapter and returned one reply without starting outreach. A repeated update did not duplicate work. A six-call outreach run reached approval and resumed without another model request.
- Simulated invalid keys, missing credits, denied access, unavailable models, bad requests, and rate limits stopped after one attempt. A temporary server failure made at most two attempts. Saved errors and Telegram notifications contained fixed explanations without provider response bodies or credentials. Existing budget accounting was retained.
- Dashboard status checks the selected xAI key, including blank/whitespace handling, without exposing it or treating other providers' keys as configured. Tests isolate exported xAI credentials alongside other settings.
- Local configuration was checked without a model request. An empty duplicate `XAI_API_KEY` was removed while preserving the entered key, and `OUTREACH_MODEL_PROVIDER=xai` was set explicitly. The shared template contains blank credentials; local credentials and databases stay outside Git.

No live xAI/Groq requests, Telegram messages, or Gmail actions were made for this change. The owner's first Telegram request after restart must still verify xAI key validity, model permissions, available credits, and real response quality. The offline checks do not establish those account conditions.

**Restart follow-up:** a reported Telegram failure was traced to the old server, started before the xAI implementation. The authenticated Connections endpoint still reported `groq`; the saved job contained two generic model failures, without enough information to identify the provider's rejection. Paused the queue, gracefully stopped the idle old process, and started the current service. Verified `/health` returned `ok`, Connections reported `xai` configured, and Telegram reported connected. The original failed run and its two recorded attempts were preserved; no new work was queued during checks. Restored the queue to its previous unpaused state. No model inference or Gmail action was performed. Setup instructions now explain how to recognize and restart an outdated process.

**Account-access follow-up:** the owner's next Telegram retry reached xAI and returned HTTP 403. The application saved the safe explanation and stopped after one attempt, as intended. A separate read-only `GET /v1/api-key` diagnostic returned HTTP 200: the key was neither disabled nor individually blocked, allowed the configured `grok-4.3` model and all endpoints, but reported `team_blocked: true`. This identifies a team restriction, not its cause; the endpoint does not expose the credit balance. No inference request was made during the diagnostic, and no permissions or billing settings were changed. The owner must inspect the team's billing/account notices or contact xAI support before another model test. Successful live model output remains unverified.

## Model failure explanations — October 10, 2026

- **391 tests passed**, including local Chromium/OCR, with `RUN_BROWSER_TESTS=1 RUN_OCR_TESTS=1 .venv/bin/python -m pytest -o addopts='' -q`.
- Simulated invalid keys, organization/project model blocks, bad requests, rate limits, and temporary server failures through the Groq adapter and chat worker. Verified safe saved errors/Telegram notifications, bounded retries, unchanged budget accounting, and credential redaction.
- Dashboard JavaScript syntax and Git whitespace checks passed. Budget labels now distinguish reservations from actual billing.
- A separate live diagnostic accepted the configured Groq key and found the model in its catalog, but a generic greeting request returned `403 model_permission_blocked_org`. No successful live response was obtained. No Telegram or Gmail message was sent during diagnosis. Further calls with that key stopped at the owner's request.

## Natural Telegram conversation — October 10, 2026

| Check | Result |
|---|---|
| Complete automated suite | **376 passed** with `RUN_BROWSER_TESTS=1 RUN_OCR_TESTS=1 .venv/bin/python -m pytest -o addopts='' -q`. Includes real local Chromium and OCR fixtures, with simulated external APIs. |
| Ordinary messages and memory | A greeting queues a chat job, not outreach. Follow-up context survives reopening SQLite. Consecutive queued messages see preceding completed answers. `/new` resets context; `/guided` and `/chat` switch modes. |
| Files and public research | A captioned text upload is extracted before answering. Responses retain file/page or public-web references. Unattached files, private/guessed URLs, and links beyond one level are blocked. Missing search is reported without inventing search results. |
| Durability and usage | Duplicate updates and replay after enqueue reuse the job/conversation. Saved answers survive interrupted delivery without another model call. Explicit retry retains spent budgets. Queue pause, cancellation, model/tool bounds, and six-exchange history limits pass. |
| Outreach boundary | A normal chat request produces a concrete proposal. Starting it enters the existing graph; repeated starts cannot duplicate the run. Follow-ups invalidate older proposals. A fake browser/model/Gmail flow still pauses for exact-message approval before one simulated Gmail draft. Unknown model actions cannot send mail. |
| Background separation | A resume can be summarized in chat without its private background text being carried into prospect research evidence. Its background role remains attached to the outreach request. |
| Service smoke check | An authenticated request to the demo Telegram endpoint queued a chat job, the real background worker produced a simulated Telegram reply, health stayed `ok`, and the outreach-run count stayed zero. The updated Mermaid diagram was rendered and visually inspected. |
| Existing quality checks | All four simulated outreach evaluations pass. These score reference cases and workflow behavior, not live conversational intelligence. |

No live Telegram/Groq/Gmail calls were made for this change. Credentials and local databases were preserved. The account-connected check is to restart normal mode, send “Hi,” ask about an uploaded file or supplied public URL, ask a follow-up, and then request outreach. Search discovery needs a Brave key; supplied URLs and files do not. Conversation is currently available in Telegram; the dashboard lists jobs/usage and controls outreach, rather than displaying a chat transcript.

## File reading — October 8, 2026

| Check | Result |
|---|---|
| Automated suite | **358 passed** with `RUN_BROWSER_TESTS=1 RUN_OCR_TESTS=1 python -m pytest -o addopts='' -q`. Includes 31 file-related checks and all retained outreach checks. No provider credentials or external API calls. |
| Real local extraction | Read native two-page PDFs, DOCX/ODT text, HTML, and text formats. Installed Tesseract and read both a PNG and a scanned PDF. Verified page references, text limits, malformed input, and missing-OCR errors. |
| Durable jobs and boundaries | Checked duplicate uploads, interrupted-job retry, owner authentication, oversized uploads, Telegram owner filtering, bounded downloads, large Unicode subprocess output, parser cancellation, and excluded provider credentials. Background evidence survives checkpoint serialization. |
| File-to-search flow | An uploaded source reached goal interpretation, a search query, sourced prospects, and human approval using fake external services. Email addresses found in private files required owner selection. Shortened input kept complete source references. A full fake Telegram upload conversation completed approval and one fake Gmail draft. |
| Dashboard walkthrough | Real Chromium uploaded a two-page PDF, previewed extracted sections, started document-only research, and approved one simulated Gmail draft. The saved run retained both pages and used the original six model calls. Desktop and 390-pixel mobile views were inspected; no JavaScript errors or horizontal overflow. |
| Simulated evaluations | All four existing outreach scenarios passed every reference check with six scripted model calls each. |
| Installed package | Built a wheel, installed it into a fresh Python 3.12 environment, and ran outside the repository. The installed worker read native/scanned PDFs, PNG, and DOCX; reopened storage retained all four ready records. |
| Documentation | Updated supported formats, OCR installation, upload API, phase/file guide, and the actual workflow diagram. |

Manual checks used isolated temporary storage and fictional files. File extraction and browser UI interaction were real; search/model/Gmail responses were simulated. Existing credentials and application data were preserved. Live Telegram file delivery and live model interpretation of uploaded material still need the configured account checks below.

## Connected application — October 7, 2026

The connected application is implemented and its local flow is verified. The checks below distinguish real local execution from simulated external services.

| Check | Result |
|---|---|
| Existing behavior after moving the core | 285 retained tests passed; tests for removed CLI/research-only entry points were retired. |
| Final automated suite | **327 passed** with `RUN_BROWSER_TESTS=1 python -m pytest -o addopts='' -q`. Includes actual Chromium against a local fixture; no external-service credentials or public API calls. |
| Simulated evaluations | All four scenarios—academic, jobs, sales, networking—completed. Each used six scripted model calls and passed the reference scoring checks. This does not measure a live model’s quality. |
| Telegram-to-Gmail flow | Fake Telegram drove the real service/graph through goal → fake browser evidence → qualification/contact checks → draft/review → approval → one fake Gmail draft. The dashboard service submitted Telegram’s saved choice; stale buttons did not repeat the action. |
| Browser network restrictions | Real Chromium rendered JavaScript from a local fixture and blocked POST requests, private destinations, and a private redirect. Unit checks also cover mixed DNS answers and persistent limits. |
| Public-page smoke check | `BrowserClient` successfully read `https://example.com` with the production public-network proxy and sandboxed Chromium. |
| Dashboard walkthrough | Real Chromium exercised login, new research, recipient evidence, automated review, approval, fake Gmail drafting, saved message inspection, overview, Connections, and reply checking. Desktop and 390-pixel mobile layouts were inspected; no JavaScript errors or mobile horizontal overflow. |
| Gmail OAuth behavior | Mocked tests passed for encrypted storage, renewal, revoked access, required scopes, session-bound one-use state, verified email, same-account reconnect, changed-account blocking, and disconnect cleanup. |
| Restart and duplicate protection | A packaged service was stopped at approval, restarted, and approved through HTTP. It retained the pending draft, kept the original six model calls, returned the original job for a repeated request, and recorded one fake Gmail draft. |
| Cancellation and queue controls | Tests passed for queue pause, cancellation before another node, and recording an external action already underway. All prospects must have a decision before a batch resumes. |
| Data preservation and instance lock | Migration tests adopted earlier contact tables without losing opt-outs. A second instance using the same data directory was rejected. Interrupted claimed jobs required explicit retry. |
| Clean installation and packaging | Installed into a fresh Python 3.12 environment. Built and installed a wheel; started it from outside the repository. Dashboard assets, migrations, authentication, health, research, and saved approval worked. |
| Documentation/assets | Updated file guide, setup/API instructions, current plan, and Mermaid/SVG diagram. JavaScript syntax, Python compilation, and Git whitespace checks passed. |

Existing local `.env` credentials and database files were preserved. Manual service checks used isolated temporary data directories and simulated Gmail/model/search/Telegram clients.

## Checks that still need the owner's environment

- **Real Telegram delivery:** configure the bot token and owner ID, then test normal messages, a file/web question, a follow-up, and an outreach proposal. `/guided` remains available for the original step-by-step flow.
- **Real Google connection and actions:** configure the Google web client and encryption key, complete consent, create an approved draft addressed to yourself, then explicitly enable and approve a separate test send to yourself. No real Gmail draft or email was created during this implementation.
- **Live model quality:** configure the selected xAI, Groq, or OpenAI key and review real sourced results. The simulated eval scores are not live model benchmarks.
- **Docker build/run and Linux hosting:** Docker is not installed on the development machine. Dockerfile/Compose packaging is provided, but a container build and host-specific Chromium sandbox operation have not been verified. Remote hosting has not been performed.

Follow [setup](SETUP.md) for these checks. Local implementation is complete; live connector acceptance remains separate until the configured accounts and hosting environment are exercised.
