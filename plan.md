# Telegram outreach application: implementation plan

Replace the old CLI and research-only entry points with one application shared by a private Telegram bot and an authenticated dashboard. Keep the tested outreach behavior and local SQLite data. Groq remains the chosen provider.

## Implemented delivery steps

1. **Consolidate the core:** organize agent, domain, model providers, connectors, services, storage, and web packages. Remove retired entry points. Implement saved background jobs and Telegram conversations/approvals.
2. **Connect Gmail:** owner login, Google OAuth, encrypted renewable credentials, account-bound approvals, drafts, guarded sends, and on-demand reply checks.
3. **Browser research:** public pages, bounded navigation, evidence and public email collection, recipient selection, and a fake tool for tests.
4. **Dashboard:** statistics, account status, run details, sources, drafts, logs, approvals, cancellation, retries, and queue controls using the same service as Telegram.
5. **Validate and package:** schema migrations, restart recovery, health, single-instance protection, Docker packaging, accurate guides, and verified commits.

## Implemented file-reading extension

Telegram and dashboard goals accept PDFs, images/scans, DOCX/ODT, and supported text files. Durable jobs extract text locally with PDFium and Tesseract OCR. Files marked background personalize the goal/messages; research files supply cited evidence. The existing interpretation call uses relevant file details to guide search. Saved filename/page references, visible extraction limits, owner confirmation for file-origin email addresses, and restart/retry behavior are included. See [file setup](docs/SETUP.md#read-files-and-use-them-for-research) and phase 37 in the [file guide](FILE_GUIDE.md).

## Implemented natural conversation extension

Ordinary Telegram messages enter a bounded LangGraph conversation loop. It remembers recent exchanges, answers questions, reads attached files/public pages, searches when configured, and inspects outreach progress. A requested outreach campaign becomes a reviewable request with a Start outreach button, then uses the existing outreach graph and exact-message approval. `/new` is an optional history reset; `/guided` retains the step-by-step form. Durable chat jobs reuse existing SQLite tables and persistent usage limits. Phase 39 in the file guide records implementation and validation; live model/chat quality remains a separate account check.

## Acceptance

Telegram goal → public browser research → qualification and contact checks → strategy and reviewed draft → current human approval → Gmail action → saved outcome. The dashboard shows the same run. Restarting preserves pending approvals without duplicate actions. Automated tests require no live services. Live integration checks are recorded separately and require configured accounts.

## Verification status

The service, connectors, dashboard, migrations, Docker configuration, and natural conversation layer are implemented. All 376 automated checks pass, including real local Chromium, image OCR, and scanned-PDF fixtures. The four simulated evaluation scenarios pass. Earlier packaging validation started a fresh installed package outside the repository and resumed a saved approval after restart without repeating research or a Gmail action.

Real Telegram delivery, Google consent and Gmail draft/send checks, live model quality, and Docker execution remain environment checks. No live Google account was connected or messaged during implementation, and Docker is unavailable on this machine. Details are recorded in [local validation](docs/VALIDATION.md).

## Defaults

One owner and Gmail account; natural Telegram conversation with an optional guided mode; public research only; up to five page visits per run; one job worker; SQLite; chat proposals save in the app unless Gmail is requested; sends explicitly enabled and approved; reply checks on demand; local testing before Linux hosting.

## Historical work

Earlier phases and their verification are preserved in [phase history](docs/PHASE_HISTORY.md). The [file guide](FILE_GUIDE.md) records each completed restructuring step and explains the new code.
