# Outreach Agent

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Contributions welcome](https://img.shields.io/badge/Contributions-welcome-brightgreen.svg)](CONTRIBUTING.md)

A conversational Telegram assistant for questions, file reading, public-web research, and outreach. Emails are prepared only when you ask. The agent saves requested, reviewed drafts in Gmail and notifies you; you review, edit, and click **Send** yourself.

**Python 3.12+ · LangGraph · FastAPI · Grok (xAI)/Groq/OpenAI · SQLite or Supabase PostgreSQL + pgvector · Playwright · Telegram · Gmail**

## What it does

- Answers normal Telegram messages, remembers recent conversation, and chooses read-only tools when needed. `/new` is an optional reset; `/guided` opens step-by-step outreach setup.
- Reads uploaded PDFs, scanned pages, images, Word/OpenDocument files, and text. Uses relevant content to guide research, with filename/page references.
- Searches the web without a key using DuckDuckGo, or uses Brave when configured. Reads public websites and retains sources and published email evidence.
- Searches saved documents and website evidence across conversations by meaning and keywords, with local embeddings and cited passages. The dashboard exposes the library and live storage checks. [Supabase and search setup](docs/SUPABASE.md).
- Routes instruction following to Grok 4.3, reasoning/tool selection to Grok 4.20, and evidence analysis to 4.20 Multi-Agent. [Models and tools](docs/MODELS_AND_TOOLS.md).
- Drafts ordinary emails to recipients you already know, or researches and qualifies new contacts for outreach. Both paths review the writing and protect Gmail actions against duplicates.
- Reads existing Gmail drafts, shows proposed changes, and updates the same draft only after your approval in Telegram or the dashboard.
- Uses friendly Telegram replies, asks for missing details, and shows only **Queued…**, **Researching…**, or **Typing…** while working. Detailed progress and diagnostics stay in the dashboard. App-only drafts retain review controls.
- Saves progress across restarts. Say **stop** to pause a task and **continue** to resume it with retained evidence and usage limits.
- Connects one Gmail account with encrypted, renewable credentials. The agent cannot send emails.
- Tracks events, reported tokens, estimated budgets, confirmed Gmail actions, and on-demand reply checks.

## How it works

1. **Tell the Telegram bot what you need.** Research, file-reading, and new-draft requests start directly. It asks questions when essential details are missing.
2. **The agent gathers information.** It searches public pages, reads supplied websites/files, or retrieves relevant saved information.
3. **Read the result in Telegram.** Research returns findings and sources. Email preparation starts only when you request it.
4. **Review requested emails in Gmail.** The agent writes, checks, and saves new drafts, then notifies you. You click **Send** yourself.
5. **Approve edits before they are applied.** “Edit my latest email draft and add a short introduction” produces a preview. Approval updates that same draft.

One saved queue serves conversation and outreach. The dashboard shows the same work; **stop** and **continue** use its saved progress. An uncertain Gmail write waits for inspection before another attempt.

<details>
<summary>View the complete workflow diagram</summary>

![Telegram questions use reading tools; explicit email requests produce Gmail drafts for the owner to review and send, with persistent state](docs/assets/workflow.svg)

</details>

## Try it locally

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m app.main --demo
```

Open **http://127.0.0.1:8000** and sign in with **`demo`** (or your configured owner password). Select **New run**, keep the fictional example, and start it. Inspect the saved message and simulated Gmail draft outcome. All external services are simulated; no keys or Chromium installation are needed. Demo progress is saved separately in `.data/demo`.

Send a file in Telegram with a caption such as “Summarize this,” or attach it in the dashboard's **New run** form. Choose **My background** for a resume/profile or **Research evidence** for material to investigate. Image and scanned-PDF text needs [local Tesseract OCR](docs/SETUP.md#read-files-and-use-them-for-research); no extra model key is needed.

For your own Telegram bot, Gmail account, and public browser research, follow the [setup guide](docs/SETUP.md). Start the configured application with **`python -m app.main`**. It loads `.env` automatically.

## Checks

```bash
python -m pytest
python -m evals.run --output .data/evaluations.json
```

Tests and the default evaluations use local substitutes. The [validation record](docs/VALIDATION.md) lists completed and pending checks. Storage defaults to local SQLite and files; [Supabase setup](docs/SUPABASE.md) connects one hosted database, private file storage, and pgvector search.

## Documentation and contributions

[Setup](docs/SETUP.md) · [File guide and phases](FILE_GUIDE.md) · [API](docs/API_GUIDE.md) · [Contributing](CONTRIBUTING.md)

Open source under [MIT](LICENSE). Contributions use the same license; contributors retain their copyright. Vendored third-party material has its own [notices](THIRD_PARTY_NOTICES.md).
