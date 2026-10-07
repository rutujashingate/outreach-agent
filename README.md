# Outreach Agent

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Contributions welcome](https://img.shields.io/badge/Contributions-welcome-brightgreen.svg)](CONTRIBUTING.md)

A Telegram outreach assistant that turns your goal into sourced prospects and reviewed email drafts. A dashboard shows progress, evidence, approvals, Gmail connections, and usage. You approve the exact message before Gmail creates a draft or sends it.

**Python 3.12+ · LangGraph · FastAPI · Groq/OpenAI · SQLite · Playwright · Telegram · Gmail**

## What it does

- Researches public websites and optional Brave results; retains sources and published email evidence.
- Qualifies prospects, checks relationship history and contact rules, and writes personalized drafts.
- Shares review, edit, approve, reject, retry, and cancel controls between Telegram and the dashboard.
- Saves jobs, conversations, approvals, and workflow progress across restarts.
- Connects one Gmail account with encrypted, renewable credentials. Drafts are the default; sends require explicit enablement and approval.
- Tracks events, reported tokens, estimated budgets, confirmed Gmail actions, and on-demand reply checks.

## How it works

![Telegram and dashboard share a saved queue, LangGraph research and message workflow, human approval, Gmail actions, and SQLite persistence](docs/assets/workflow.svg)

One worker executes the workflow. Approval resumes the same run. Uncertain Gmail writes remain blocked for inspection rather than being automatically repeated.

## Try it locally

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m app.main --demo
```

Open **http://127.0.0.1:8000** and sign in with **`demo`** (or your configured owner password). Select **New run**, keep the fictional example, then approve its draft and submit your decision. All external services are simulated; no keys or Chromium installation are needed. Demo progress is saved separately in `.data/demo`.

For your own Telegram bot, Gmail account, and public browser research, follow the [setup guide](docs/SETUP.md). Start the configured application with **`python -m app.main`**. It loads `.env` automatically.

## Checks

```bash
python -m pytest
python -m evals.run --output .data/evaluations.json
```

Tests and the default evaluations use local substitutes. The [validation record](docs/VALIDATION.md) lists completed checks and live account checks. Normal storage uses two SQLite files—application records and workflow checkpoints—not two database servers.

## Documentation and contributions

[Setup](docs/SETUP.md) · [File guide and phases](FILE_GUIDE.md) · [API](docs/API_GUIDE.md) · [Contributing](CONTRIBUTING.md)

Open source under [MIT](LICENSE). Contributions use the same license; contributors retain their copyright. Vendored third-party material has its own [notices](THIRD_PARTY_NOTICES.md).
