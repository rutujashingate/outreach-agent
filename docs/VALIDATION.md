# Local validation

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
