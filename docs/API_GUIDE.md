# Application API

Telegram and the dashboard call one shared service. The API is intended for one owner. Long-running work is saved first and returns **HTTP 202** with `id` (job ID), `run_id` when applicable, `kind`, `status`, timestamps, and any error. Poll the saved run instead of keeping a request open.

## Authentication

The dashboard calls `POST /auth/login` with `{"password":"..."}`. The response sets an HttpOnly session cookie and returns `csrf`. Browser mutations send that value in `X-CSRF-Token`; if an Origin header is present it must match `OUTREACH_APP_URL`. `GET /auth/session` restores the current session and `POST /auth/logout` ends it. Sessions expire on service restart; saved run decisions remain.

Scripts can instead send `X-API-Key` matching the optional `OUTREACH_API_KEY`. Do not place credentials in URLs. Google connect/callback additionally require a browser owner session.

Use a stable `Idempotency-Key` header for each intended queued action. Repeating it returns the original job, even after completion. Use a new key for a different operation. Keys contain 1–100 ASCII characters; they share a namespace across `/api` job routes. Telegram supplies its own separate update-based keys.

## Routes

| Method and path | Purpose |
|---|---|
| `GET /health` | Public service liveness: 200 `ok`, or 503 if a background task stopped. No private data. |
| `GET /` | Dashboard login shell; data requires authentication. |
| `POST /api/documents?filename=notes.pdf` | Upload raw file bytes, save an extraction job, and return 202 with `{document, job}`. |
| `GET /api/documents?page=1` | List saved file metadata, 20 records per page. Optional `ids=ID1,ID2` looks up at most five references. |
| `GET /api/documents/{id}` | Inspect saved metadata, extraction status, pages, warnings, or error. |
| `POST /api/documents/{id}/retry` | Explicitly retry a failed file; returns 202 with `{document, job}`. |
| `GET /api/overview` | Run statistics, current queue/worker status, recent jobs, usage, and connector status. |
| `GET /api/runs?page=1&limit=20` | Paginated outreach history; up to 100 records per page. |
| `POST /api/runs` | Validate a goal and queue a new run. Returns 202. |
| `GET /api/runs/{id}?event_page=1` | Saved state, current executing step, pause flags, metadata, choices, usage, and 50 newest-first events per page. |
| `POST /api/runs/{id}/choices` | Save one current approve/reject/edit selection shared with Telegram. Does not resume work yet. |
| `POST /api/runs/{id}/submit` | Queue all saved choices as one validated batch; returns 202. |
| `POST /api/runs/{id}/decisions` | Submit a full `{"decisions":[...]}` batch directly; returns 202. |
| `POST /api/runs/{id}/recipients` | Resolve all pending addresses or skips; returns 202. |
| `POST /api/runs/{id}/retry` | Queue an explicit retry of failed/interrupted execution; returns 202. |
| `POST /api/runs/{id}/cancel` | Save a stop request and cancel queued work; returns 202 with run ID and `cancel_requested` status. This is a control flag, not a new job. |
| `PUT /api/queue` | Set `{"paused":true}` or `false`; does not interrupt an active job. |
| `PUT /api/profile` | Save sender `name`, optional `email`, and `context` for new Telegram/dashboard requests. |
| `POST /api/replies/check` | Queue an on-demand check; returns 202 with a job ID and no outreach run ID. |
| `GET /api/connectors` | Gmail account status, Telegram health, browser availability, model/search configuration presence, document/OCR availability, sender profile, and storage backend/checkpoint mode. No tokens or database URLs. |
| `POST /api/connectors/gmail/connect` | Return the Google consent URL for the logged-in browser session. |
| `GET /api/connectors/gmail/callback` | Google’s registered redirect; validates the one-use state and owner session, then returns to the dashboard. |
| `POST /api/connectors/gmail/disconnect` | Remove encrypted local credentials and attempt revocation at Google. |

The retired `/outreach`, `/runs`, interactive CLI, and public OpenAPI docs are not entry points in this application.

## Start a run

Example JSON for `POST /api/runs`:

```json
{
  "goal": "Prepare outreach email drafts for AI infrastructure teams that could benefit from API observability.",
  "sender": {
    "name": "Your Name",
    "context": "Describe only the product or experience you actually offer."
  },
  "research_material": "",
  "use_search": true,
  "use_browser": true,
  "seed_urls": [],
  "discover_emails": true,
  "recipients": {},
  "gmail_action": "draft"
}
```

Posting a run is an explicit instruction to prepare emails. Gmail fills a missing sender address from the connected account. A supplied address must match it for draft creation. Known recipients can be supplied by prospect ID or matching target name, for example `{"Example AI":{"email":"person@example.com"}}`; these take precedence over discovered addresses. To work without Gmail, choose `gmail_action: "none"` and provide recipient addresses for contact checking. Draft is the UI default; the underlying reusable request record defaults to `none`.

The trimmed goal must contain 1–2,000 characters. Booleans must be real JSON booleans, fields must be recognized, notes are bounded to 100,000 characters, and seed URLs to five. Invalid input returns 422, including `gmail_action: "send"`. A configured browser is required for `use_browser`; a Brave key for `use_search`. Requested Gmail drafts are saved after automated review and contact checks. The owner reviews and sends them manually in Gmail; no configuration flag enables agent sending.

## Upload and attach files

Send the file bytes as the request body of `POST /api/documents?filename=notes.pdf` with `Content-Type: application/octet-stream`. Use the same API-key or browser-session/CSRF authentication as other mutations. This route takes raw bytes, not a multipart form. It rejects empty/unsupported inputs and caps the stream at 10 MiB; larger uploads receive 413.

The 202 response contains `document.id`, `document.status`, and the queued `job`. File status moves through `queued` → `processing` → `ready` or `failed`. Repeating identical bytes with the same extension reuses the original saved file and job. A renamed duplicate keeps its first filename. A failed read needs the explicit retry route with a fresh idempotency key.

Poll `GET /api/documents/{id}`. Once ready, `content.pages` contains `number`, `text`, and `method` (`text` or `ocr`); `content.warnings` explains extraction limits. The metadata records the filename, checksum, size, and retrieval time. There is no unauthenticated or original-file download endpoint.

Include references when creating a run:

```json
{
  "goal": "Prepare outreach drafts for research groups that match my uploaded resume.",
  "attachments": [
    {"document_id": "COPY_32_CHARACTER_ID_FROM_UPLOAD", "purpose": "background"}
  ],
  "use_search": true,
  "use_browser": true,
  "discover_emails": true,
  "gmail_action": "draft"
}
```

Use `purpose: "research"` for prospect evidence; `background` describes the sender. At most five unique file references are accepted. Unknown files receive 404; failed files must be retried or removed before starting. A queued extraction runs ahead of its outreach job on the shared worker. Uploading alone makes no model call. Run details include `attached_documents` metadata and `state.documents` with loaded, saved evidence. Research references look like `document:FILE_ID#page=2`. Addresses found in private files pause for owner selection.

## Review and resume

New `gmail_action: "draft"` runs save reviewed drafts without an in-app approval pause. Their outcomes include the Gmail draft ID and a `message_fingerprint` binding the account, recipient, content, and action. Review/edit/send the actual saved draft in Gmail. The following controls remain for `none` (app-only) drafts and older pending approvals; old send-mode runs are blocked.

Read `state.approval_requests` from the run details. Use the exact current `prospect.id`, `version`, and `fingerprint`:

```json
{
  "prospect_id": "p1",
  "version": 1,
  "fingerprint": "COPY_THE_CURRENT_FINGERPRINT_FROM_THE_RUN",
  "action": "approve"
}
```

POST one such object to `/choices`, then call `/submit` after every pending prospect has a selection. `action` may be `approve`, `reject`, or `edit`. An edit also includes:

```json
{
  "edited_draft": {
    "prospect_id": "p1",
    "subject": "Your revised subject",
    "body": "Your revised message"
  }
}
```

An edit creates a new message version, triggers review, and requires a new approval. The fingerprint binds the sender account, recipient, exact message, and intended action. Staging an old decision returns 409; a malformed complete batch returns 422. One pending batch is queued per run; two interfaces cannot resume it simultaneously.

For a run with `awaiting_recipients: true`, resolve every ID in `state.recipient_requests`:

```json
{
  "recipients": {
    "p1": {"email": "person@example.com"},
    "p2": null
  }
}
```

`null` means skip this prospect. Selecting a known candidate retains its published source and evidence quote; another address is recorded as explicitly supplied by the owner.

## Status and failures

Run status is `queued`, `running`, `paused`, `completed`, `failed`, or `cancelled`. `current_step` in details reports the active node while running, and the saved step otherwise. `state.current_step` is the durable completed/paused snapshot. Outcomes distinguish approved-only, drafted, sent, rejected, blocked, failed, manual-review, and uncertain results. A completed run can contain blocked or failed prospects; inspect each outcome.

401 means authentication is needed; 403 means a browser request failed its origin/token check; 404 means an unknown run/route; 409 means conflicting or stale work; 422 means invalid input; 429 means a request/budget limit; 502/503 means a connector/configuration problem. Job errors retain a generic error type; inspect per-run events and Connections for context.

An uncertain Gmail result is not automatically retryable. The action ledger and contact lock remain in place. Inspect Gmail manually before any maintenance resolution. Statistics count **drafts** only after a confirmed Gmail draft response. `sent` retains historical agent-send records, if present; new agent sends are blocked. Manual Gmail sends are not automatically reconciled into that counter.

## Fake Telegram walkthrough

In `--demo` mode only, authenticated `POST /api/demo/telegram` accepts `{"text":"Hello"}`, `{"text":"/guided"}`, or `{"callback_data":"..."}`. Ordinary messages queue conversation jobs; the demo model returns a clearly labeled simulated reply. `/guided` opens the complete fictional outreach walkthrough. `/new` now resets the conversation. Use the returned inline keyboard’s `callback_data` for button presses. The normal background worker executes jobs. This endpoint returns 404 in a normal runtime.

See `tests/test_telegram.py` for guided outreach with fake Telegram/browser/model/Gmail services, and `tests/test_conversation.py` for normal messages, source reading, saved follow-ups, recovery, and the handoff to the same approval workflow. Chat jobs have kind `chat`; they contribute to usage and job statistics without inflating the outreach-run count. Run details, cancellation, and explicit retry also work for their run IDs. Their conversation history is currently presented in Telegram, not as a dashboard chat interface.
