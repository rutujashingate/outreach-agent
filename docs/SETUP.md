# Setup and daily use

Run commands from the project folder with Python 3.12+. [Troubleshooting](TROUBLESHOOTING.md) covers connection errors and recovery.

## 1. Install

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m playwright install chromium
```

To try the dashboard without accounts, run `python -m app.main --demo`. Open **http://127.0.0.1:8000** with password **`demo`** (or your configured owner password). The demo uses fake services and separate local data; it does not connect your Telegram bot.

## 2. Fill in `.env`

Copy `.env.example` to `.env` **only if `.env` does not exist**. Keep existing credentials and use one entry per setting.

| Required for Telegram | Value |
|---|---|
| `OUTREACH_OWNER_PASSWORD` | A password you choose for the dashboard. |
| `XAI_API_KEY` | Your private key from [xAI Console](https://console.x.ai/). |
| `OUTREACH_TELEGRAM_BOT_TOKEN` | Your bot's token from **@BotFather**. |
| `OUTREACH_TELEGRAM_OWNER_ID` | Your numeric user ID, found below. |

The template selects xAI and the three [model roles](MODELS_AND_TOOLS.md). Leave `OUTREACH_APP_URL=http://127.0.0.1:8000` for local use. Keys stay in `.env`, outside Git and Telegram messages.

| Optional connection | What to configure |
|---|---|
| Gmail drafts and reads | Google client ID/secret and encryption key; see step 4. |
| Brave search | `BRAVE_SEARCH_API_KEY`; otherwise DuckDuckGo works without a key. |
| Hosted data and saved knowledge | Follow [Supabase setup](SUPABASE.md). SQLite works without database credentials. |
| Image/scanned-PDF reading | Install local OCR; see [file reading](#read-files-and-use-them-for-research). |

<details>
<summary>Using Groq or OpenAI instead</summary>

| Provider | `.env` settings |
|---|---|
| Groq | `OUTREACH_MODEL_PROVIDER=groq`, `GROQ_API_KEY`, `GROQ_MODEL` (default `openai/gpt-oss-120b`). |
| OpenAI | `OUTREACH_MODEL_PROVIDER=openai`, `OPENAI_API_KEY`, `OPENAI_MODEL`. |

Only the selected provider's key is used. The three-role routing is the xAI path. An absent provider setting keeps the older Groq default.

</details>

## 3. Connect Telegram and start

1. Create a bot through **@BotFather** using `/newbot`. Save its token in `.env`.
2. Open that bot from your own account and send `/start`.
3. With the service stopped, find your numeric ID using the snippet below; save it in `OUTREACH_TELEGRAM_OWNER_ID`.
4. Start the service and keep it running:

```bash
source .venv/bin/activate
python -m app.main
```

Open **http://127.0.0.1:8000**, sign in, and check **Connections**. Send **Hi** to your bot. The bot accepts only your private chat. It uses long polling and needs no public webhook.

<details>
<summary>Find your numeric Telegram user ID</summary>

This reads your bot token locally and prints only private-chat sender IDs:

```bash
python - <<'PY'
import os
import httpx
from dotenv import load_dotenv
load_dotenv('.env')
token = os.environ['OUTREACH_TELEGRAM_BOT_TOKEN']
response = httpx.post(f'https://api.telegram.org/bot{token}/getUpdates',
                      json={'timeout': 0}, timeout=15).json()
for update in response.get('result', []):
    message = update.get('message', {})
    if message.get('chat', {}).get('type') == 'private':
        print(message.get('from', {}).get('id'))
PY
```

Save **your** sender number. [Telegram bot setup](https://core.telegram.org/bots/tutorial#obtain-your-bot-token).

</details>

**Restart:** press **Ctrl+C** in the service terminal, then run `python -m app.main` again. Code and `.env` changes require a restart. Use one running instance per bot/data directory.

## 4. Connect Gmail

<details>
<summary>Google account setup — open when you want Gmail drafts</summary>

1. In [Google Cloud Console](https://console.cloud.google.com/), create/select a project and enable **Gmail API**.
2. In **Google Auth platform**, configure Branding and External audience. Keep the app in Testing and add your Gmail address as a test user.
3. In **Data Access**, add `https://www.googleapis.com/auth/gmail.readonly` and `https://www.googleapis.com/auth/gmail.compose`.
4. Create a **Web application** client under **Clients**. Register this exact redirect URI:

```text
http://127.0.0.1:8000/api/connectors/gmail/callback
```

5. Save `OUTREACH_GOOGLE_CLIENT_ID` and `OUTREACH_GOOGLE_CLIENT_SECRET` in `.env`. If `OUTREACH_SECRET_KEY` is missing, generate it once:

```bash
python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

Save the result as `OUTREACH_SECRET_KEY`. Keep it: replacing it makes saved tokens unreadable. Leave `OUTREACH_READ_GMAIL=true` to use relevant conversation history.

6. Restart the service. In **Connections → Connect Google**, sign in and grant access. Confirm your email address appears. Telegram and the dashboard share this account; adding client credentials alone does not connect Gmail.

Tokens are encrypted and renew automatically. Reconnect if Google expires/revokes access. The app blocks sending even though Google's compose permission includes it. [Google consent setup](https://developers.google.com/workspace/guides/configure-oauth-consent) · [Gmail scopes](https://developers.google.com/workspace/gmail/api/auth/scopes).

</details>

## Use the bot

![Creating and editing emails follow separate paths; existing-draft updates need your approval](assets/email-flow.svg)

| Try | Expected result |
|---|---|
| “Find funded wearable startups” | Web research with sources. Brave is optional. |
| “Read https://example.com” | The browser reads that public page. |
| “Draft a short test email to friend@example.com” | Writing/review starts directly, then saves a Gmail draft. |
| “Edit my latest email draft and add a short introduction” | Proposed changes; **Approve changes** updates the same draft. |
| **stop**, then **continue** | Resume the saved task and evidence. Pending approvals still need your decision. |

New drafts start when requested. Ask to see a plan first if you want preparation to wait. Sending stays manual in Gmail. Telegram shows **Queued…**, **Researching…**, or **Typing…**; detailed activity stays in the dashboard.

<details>
<summary>Useful commands</summary>

| Command | Purpose |
|---|---|
| `/help`, `/account` | Help or connected Gmail address. |
| `/new` | Optional conversation reset; saved runs remain. |
| `/guided`, `/chat` | Guided outreach setup or normal conversation. |
| `/runs`, `/status RUN_ID`, `/review RUN_ID` | Find saved work, inspect progress, review decisions. |
| `/recipients RUN_ID` | Resolve missing/ambiguous addresses. |
| `/stop [RUN_ID]`, `/continue [RUN_ID]` | Stop/resume a specific saved task. |
| `/retry RUN_ID`, `/cancel RUN_ID` | Retry a failure or permanently cancel. |
| `/files`, `/clearfiles`, `/retryfile FILE_ID` | Inspect, detach, or retry attached files. |
| `/replies` | Check tracked Gmail conversations for replies. |

</details>

## Read files and use them for research

Upload a document/photo with “Summarize this” or “Extract the company names.” Choose **My background** for your resume/profile and **Research evidence** for target information. Use `/files` or dashboard **Inspect text** to check extraction.

| Format | Reader |
|---|---|
| PDF | Selectable text; OCR for scanned pages. |
| PNG, JPEG, WebP, TIFF, BMP | OCR: converts printed image text into words. |
| DOCX, ODT | Main document text. |
| Text, Markdown, CSV, JSON, YAML, XML, HTML | Text extraction; content is never executed. |

<details>
<summary>Install OCR and check file limits</summary>

macOS:

```bash
brew install tesseract
```

Debian/Ubuntu:

```bash
sudo apt-get update
sudo apt-get install tesseract-ocr tesseract-ocr-eng
```

The Docker image includes English OCR. Other languages need matching language data and `OUTREACH_OCR_LANGUAGES` (default `eng`).

Defaults: **5 files/run · 10 MiB/file · 20 pages/frames · 16 megapixels/image · 40,000 extracted characters/file**. Chat uses bounded excerpts and reports shortening. OCR can misread names/addresses; inspect its output. Password-protected PDFs, legacy `.doc`, spreadsheets, and archives are unsupported. Clearing attachments does not delete saved originals.

</details>

## Check your connected application

| Check | Where / how |
|---|---|
| Service | Open `/health`; all four components should be running with Telegram enabled. |
| Accounts/tools | **Connections**; a configured model key still needs a successful live reply. |
| Files/search | Ask for a file summary and public-web research; inspect their sources. |
| Storage | **Connections → Validate storage**; resume the queue first. |
| Email creation | Request a test draft to yourself and inspect it in Gmail. |
| Email editing | Request a revision; confirm approval updates the same draft and rejection leaves it alone. |
| Recovery | Stop a task, restart the service, then continue. |

Live model requests consume provider credits. The dashboard's reserved budget is an estimate, not a bill. Defaults allow five drafts, five pages, and two searches per run. [Limits and failure help](TROUBLESHOOTING.md) · [Latest verification](VALIDATION.md).

<details>
<summary>Developer checks and Docker</summary>

```bash
python -m pytest
RUN_BROWSER_TESTS=1 RUN_OCR_TESTS=1 python -m pytest
python -m evals.run --output .data/evaluations.json
```

Browser/OCR checks need Chromium/Tesseract. PostgreSQL tests need the `postgres` extra and local `initdb`/`pg_ctl`: `RUN_POSTGRES_TESTS=1 python -m pytest tests/test_supabase_storage.py`. Tests/default evaluations use fake external services. The authenticated [API guide](API_GUIDE.md) documents endpoints; `/docs` is disabled.

```bash
docker compose up --build -d
docker compose logs -f outreach
docker compose down
```

Compose uses `.env`, localhost port 8000, and a persistent `outreach_data` volume. `down` retains data; `down -v` removes it. Chromium requires a host supporting unprivileged user namespaces. Docker execution and remote hosting remain unverified; validate locally first.

</details>
