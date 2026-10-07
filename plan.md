# Telegram outreach application: implementation plan

Replace the old CLI and research-only entry points with one application shared by a private Telegram bot and an authenticated dashboard. Keep the tested outreach behavior and local SQLite data. Groq remains the chosen provider.

## Implemented delivery steps

1. **Consolidate the core:** organize agent, domain, model providers, connectors, services, storage, and web packages. Remove retired entry points. Implement saved background jobs and Telegram conversations/approvals.
2. **Connect Gmail:** owner login, Google OAuth, encrypted renewable credentials, account-bound approvals, drafts, guarded sends, and on-demand reply checks.
3. **Browser research:** public pages, bounded navigation, evidence and public email collection, recipient selection, and a fake tool for tests.
4. **Dashboard:** statistics, account status, run details, sources, drafts, logs, approvals, cancellation, retries, and queue controls using the same service as Telegram.
5. **Validate and package:** schema migrations, restart recovery, health, single-instance protection, Docker packaging, accurate guides, and verified commits.

## Acceptance

Telegram goal → public browser research → qualification and contact checks → strategy and reviewed draft → current human approval → Gmail action → saved outcome. The dashboard shows the same run. Restarting preserves pending approvals without duplicate actions. Automated tests require no live services. Live integration checks are recorded separately and require configured accounts.

## Verification status

The new service, connectors, dashboard, migrations, and Docker configuration are implemented. All 327 automated checks pass, including a real local Chromium fixture. The four simulated evaluation scenarios pass. A fresh installed package was started outside the repository and resumed a saved approval after restart without repeating research or a Gmail action.

Real Telegram delivery, Google consent and Gmail draft/send checks, live model quality, and Docker execution remain environment checks. No live Google account was connected or messaged during implementation, and Docker is unavailable on this machine. Details are recorded in [local validation](docs/VALIDATION.md).

## Defaults

One owner and Gmail account; guided Telegram conversation; public research only; up to five page visits per run; one job worker; SQLite; draft mode by default; sends explicitly enabled and approved; reply checks on demand; local testing before Linux hosting.

## Historical work

Earlier phases and their verification are preserved in [phase history](docs/PHASE_HISTORY.md). The [file guide](FILE_GUIDE.md) records each completed restructuring step and explains the new code.
