# Outreach Agent

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Contributions welcome](https://img.shields.io/badge/Contributions-welcome-brightgreen.svg)](CONTRIBUTING.md)

A Python outreach assistant that turns a goal and supporting evidence into researched prospects and personalized email drafts. It saves progress and pauses for your approval before creating a Gmail draft.

**Stack:** Python 3.12+, LangGraph, FastAPI, Pydantic, Groq/OpenAI, SQLite, Brave Search, Gmail API.

## Features

- Research from supplied notes or optional web search, with retained source URLs.
- Prospect qualification, relationship history, and contact rules.
- Personalized strategy, email generation, and automated draft review.
- Human approval, rejection, editing, and saved-run resume through the CLI.
- Persistent call limits, estimated budgets, token usage events, and duplicate-action protection.
- REST API, 360 automated tests, and four starter evaluation scenarios.

## Workflow

![Architecture flowchart: goal, CLI or API, state, workflow coordinator, interpretation, research, prospects, qualification, memory, contact policy, strategy, writer, reviewer, human approval, optional Gmail action, outcome, and memory update](docs/assets/workflow.svg)

This follows the [architecture and phases](plan.md#remaining-phases), including stop paths, bounded revisions, and pause/resume. Rewrites and edits share one revision. The CLI supports approved Gmail drafts; API sending requires explicit enablement. Tests and evals check the workflow separately.

## Quick start

Run from the project folder using Python 3.12 or newer:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m app.cli --demo
```

The demo uses fictional data and fake services; no API keys are required. Choose **1** to start, then **4** to review. Press Enter for the latest run ID and choose `approve`, `reject`, `edit`, or `later`. Demo data disappears on exit.

To use your own goals, copy the configuration template:

```bash
cp -n .env.example .env
```

Set `OUTREACH_MODEL_PROVIDER=groq` and fill `GROQ_API_KEY` from [Groq Console](https://console.groq.com/keys). Add `BRAVE_SEARCH_API_KEY` for web search and `GMAIL_ACCESS_TOKEN` for Gmail features. Then load the settings and start:

```bash
set -a
source .env
set +a
python -m app.cli --check-config
python -m app.cli
```

Choose **1** and enter your goal, background, notes or search choice, and known recipient addresses. The configuration check verifies setting presence; it does not authenticate credentials.

Normal runs save contacts and history in `.data/relationships.sqlite3`, and workflow progress in `.data/checkpoints.sqlite3`. Both use SQLite and are created automatically. Gmail tokens currently require manual renewal.

## Tests and evaluations

```bash
python -m pytest -q
python -m evals.run --output .data/evaluations.json
```

Both commands use local substitutes for external services. The evaluation command uses preset responses and checks the workflow and scoring; live-model evaluation is described in the file guide.

## Documentation and contributions

- [File guide](FILE_GUIDE.md): code explanations, phase history, and evaluation details.
- [API guide](docs/API_GUIDE.md): endpoints, credentials, and integration settings.
- [Contributing](CONTRIBUTING.md): development setup, checks, and pull requests.

Open source under the [MIT License](LICENSE). Contributions use the same license, and contributors retain their copyright.
