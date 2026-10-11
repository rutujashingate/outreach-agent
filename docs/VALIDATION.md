# Validation

## Last application verification — October 11, 2026

| Area | Verified result |
|---|---|
| Automated suite | **555 tests passed**, including local PostgreSQL/pgvector, Chromium, and OCR. |
| Model/tool routing | Simulated native calls select the requested roles and keep a new research task separate from old email context. |
| Gmail draft edits | Fake-service checks cover full previews, approval, same-ID updates, rejection, stale decisions, preserved attachments, and uncertain writes. |
| Restart and concurrency | Local PostgreSQL retains pending edits; concurrent approvals produce one update job. |
| Dashboard | Real Chromium exercised login, before/after preview, and approval against fake Gmail. |
| Public search | Keyless discovery returned five live public results. Funding claims still need source verification. |
| Evaluations | Four simulated outreach examples passed. This measures workflow/scoring behavior, not live model quality. |
| Connected service | Restart check retained Telegram, Gmail, and Supabase; all four background components ran and the queue was restored. |

The suite command was:

```bash
RUN_POSTGRES_TESTS=1 RUN_BROWSER_TESTS=1 RUN_OCR_TESTS=1 python -m pytest -o addopts='' -o faulthandler_timeout=30 -q --tb=short
```

**Still requires owner acceptance:** actual generated wording and a real approved Gmail replacement. Tests use fake external services. Docker execution and remote hosting remain unverified.

## Documentation refresh — phase 50

| Check | Result |
|---|---|
| Links | 80 local links across 14 Markdown files resolve, including heading anchors. |
| Diagrams | All three Mermaid sources render to SVG with accessible titles and descriptions. |
| Display | README, setup, model guide, and file guide fit desktop and mobile widths; images load and expandable instructions open. |
| History | Previous file explanations, phase records, and validation details are preserved in linked history files. |
| Git | Whitespace check passes. |

Only documentation and diagrams changed. The application test result above is from phase 49; this update does not claim another application test run.

[Complete validation history](VALIDATION_HISTORY.md) · [Run the checks yourself](SETUP.md#check-your-connected-application)
