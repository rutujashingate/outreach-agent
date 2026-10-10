# Setup and daily use

Run commands from the project directory. Python 3.12 or newer is required. The service runs one worker; both Telegram and the dashboard control the same saved runs.

## 1. Install and try the demo

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m app.main --demo
```

Open **http://127.0.0.1:8000**. The password is `demo` unless `OUTREACH_OWNER_PASSWORD` is already configured. Choose **New run**, keep the example values, and start. When the draft appears, choose **Approve draft**, then **Submit decisions**. The outcome and overview will show one simulated Gmail draft. No real messages are sent.

Demo data persists under `.data/demo`. Repeating the same approved action can be blocked by duplicate protection; use another isolated `OUTREACH_DATA_DIR` for a completely fresh demonstration. Stop the service with Ctrl+C before starting another instance on the same port.

The demo does not connect to a real Telegram bot. Automated tests run the complete guided conversation through `FakeTelegram`; the authenticated demo endpoint in the [API guide](API_GUIDE.md) also exposes it locally.

## 2. Configure your application

If you do not have `.env` yet, copy `.env.example` to `.env`. If you already have it, add the missing settings without replacing existing values. Startup loads `.env` automatically; exported environment variables take precedence.

| Setting | What it is for |
|---|---|
| `OUTREACH_OWNER_PASSWORD` | A strong password you choose for the dashboard. Required for normal browser login. |
| `GROQ_API_KEY` | Your key from [Groq Console](https://console.groq.com/keys). Used for interpretation, research reasoning, qualification, writing, and review. |
| `OUTREACH_MODEL_PROVIDER=groq` | Selects Groq. `openai` is the optional alternative and uses `OPENAI_API_KEY` plus `OPENAI_MODEL`. |
| `GROQ_MODEL` | A supported structured-output model. The template uses `openai/gpt-oss-120b` hosted by Groq; that name does not require an OpenAI account. See [Groq’s supported models](https://console.groq.com/docs/structured-outputs). |
| `OUTREACH_TELEGRAM_BOT_TOKEN` | Token for your bot, issued by Telegram’s BotFather. |
| `OUTREACH_TELEGRAM_OWNER_ID` | Your numeric Telegram user ID. The bot accepts only this user in their private chat. |
| `BRAVE_SEARCH_API_KEY` | Optional [Brave Search API](https://brave.com/search/api/) key. Finds relevant pages. Omit it when supplying URLs or notes yourself. |
| `OUTREACH_GOOGLE_CLIENT_ID`, `OUTREACH_GOOGLE_CLIENT_SECRET` | Google OAuth web-client credentials for connecting your Gmail account. |
| `OUTREACH_SECRET_KEY` | A local encryption key for saved Google credentials; generated below. It is not a Google API key. |
| `OUTREACH_OCR_LANGUAGES=eng` | Installed Tesseract language codes for reading image text. English is the default; PDF/document text needs no OCR installation. |
| `OUTREACH_READ_GMAIL=true` | Allows relevant conversation history to inform relationship checks. On-demand **Check replies** is a separate explicit action. |
| `OUTREACH_ENABLE_SENDING=false` | Keeps sending disabled. Creating drafts still requires your approval. |
| `OUTREACH_APP_URL` | The exact browser origin, initially `http://127.0.0.1:8000`. Use this same address for login and the Google callback. |

Do not put secrets in Telegram messages, goals, Git commits, or screenshots. A connection shown as “configured” only means settings are present; the provider verifies them when called.

Generate the encryption key once:

```bash
python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

Copy the result into `OUTREACH_SECRET_KEY` in `.env`. Keep that key: replacing it makes existing encrypted Google credentials unreadable. For a new account connection after losing the key, restore the key or remove the old connection through a deliberate maintenance procedure; do not overwrite database files.

Install Chromium for actual website research:

```bash
python -m playwright install chromium
```

On supported Linux hosts, `python -m playwright install --with-deps chromium` also installs system libraries. The browser runs with Chromium’s sandbox, fresh cookies, and a public-address proxy. Only HTTP/HTTPS HTML pages are read. No form submissions, downloads, or logged-in browser actions are provided. [Playwright installation documentation](https://playwright.dev/python/docs/browsers).

**Website reading without Brave:** tell Telegram “Read https://example.com and explain what it does,” substituting the website you want. The optional `/guided` flow also offers **Public URLs**. In the dashboard supply starting URLs, enable **Read public pages**, and leave **Search the web** off. The browser reads supplied/search URLs and can follow same-site links one level deep, within the five-page default limit. Brave finds starting websites from a search query. Reading uploaded files also works without Brave; URLs mentioned inside files are not automatically added as browser starting URLs.

## 3. Connect Telegram

1. Create a bot with **@BotFather** using `/newbot`, then save its token in `.env`. Follow [Telegram’s bot setup instructions](https://core.telegram.org/bots/tutorial#obtain-your-bot-token).
2. Open your new bot from your own account and send `/start`.
3. With the outreach service stopped, obtain your numeric ID from that message. This local snippet reads the token from `.env` and prints only private-chat sender IDs:

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

4. Put **your** number in `OUTREACH_TELEGRAM_OWNER_ID`. Start the service with `python -m app.main` and send “Hi” to your bot. Keep the process running while using Telegram. Normal mode connects your bot; `--demo` uses simulated services.

This application uses long polling, so it needs no public Telegram webhook. If the bot already has a webhook, remove that old configuration first; the connector reports a configuration error instead of silently replacing it. Use one running service per bot and data directory.

**Talk normally.** You do not need `/new` or a fixed sequence of answers. Try “What can you help me with?”, “Read this website and explain its product,” or upload a file with “Summarize the main findings.” Follow with questions such as “Explain the second point.” The bot keeps the last six completed exchanges in the same conversation across restarts, with bounded source excerpts. It asks for missing information when needed. Without a Brave key it can read supplied URLs/files, but cannot discover new websites through search.

If you ask for an outreach campaign, it prepares a concrete request and shows **Start outreach**. Check the goal, background, sources, and intended Gmail action; press the button or describe a change. This starts the existing research/qualification/writing workflow. It does not approve an email: the exact-message approval remains a separate step. Asking for a file summary or research answer does not automatically start outreach.

`/guided` retains the original goal → background → research options → addresses → action questions. In that optional flow, `-` reuses your saved background or indicates no known recipients. `/chat` leaves guided questions. Use the dashboard’s Connections page to save your name and accurate background before live outreach.

Each ordinary message is a durable job, so commands remain responsive during model work. Queue pause also pauses chat processing. Interrupted turns require `/retry RUN_ID`; completed replies and their outgoing messages are reused on recovery. Chat uses at most six model attempts and five tool selections per message by default, also subject to the existing search/page/cost limits. `max_chat_model_calls` and `max_chat_tool_calls` can be overridden in `OUTREACH_LIMITS_JSON`. Estimates are reservations, not provider bills. The dashboard's job list and usage totals include chat; its outreach-run list counts outreach only.

| Command | Result |
|---|---|
| Plain text or a file caption | A normal conversation, question, research request, or outreach proposal. |
| `/new` | Start a fresh conversation and detach current files; saved runs and old records remain. |
| `/guided`, `/chat` | Enter optional step-by-step setup, or return to ordinary conversation. |
| `/runs`, `/status RUN_ID` | Recent runs or current progress. |
| `/review RUN_ID` | Current draft cards with approve/reject/edit choices. |
| `/recipients RUN_ID` | Resolve missing or ambiguous recipient addresses. |
| `/retry RUN_ID`, `/cancel RUN_ID` | Retry failed work or request a stop at the next safe boundary. |
| `/files`, `/clearfiles` | Show current file IDs/status, or detach files from the goal conversation. |
| `/retryfile FILE_ID` | Queue a failed/interrupted file for another local read. |
| `/replies` | Queue a reply check for tracked Gmail conversations. |
| `/account`, `/help` | Gmail connection status or command help. |

Choose a decision for every pending prospect and submit the batch. Decisions made in the dashboard are immediately authoritative in Telegram too. Old buttons cannot approve a changed message. If Telegram delivery is uncertain, `/review` or `/status` retrieves current saved information.

## Read files and use them for research

You can supply your resume, a product brief, a research paper, prospect notes, or a screenshot of printed text. The worker reads the file locally, then the goal interpreter uses relevant details in the existing search/research workflow. For example: attach your resume as **background** and ask, “Find research groups that match my experience with API observability.” Enable web search to find new pages; choose uploaded-files research to work from the supplied evidence alone.

**In Telegram:** send a document or photo directly, with a caption such as “Summarize this PDF” or “Extract the company names.” Reading is queued before answering the caption. You can also upload without a caption and then ask a question. `/files` shows progress and file IDs. A caption of `background` selects that purpose; **Use as research / Use as my background** buttons let you change it. In `/guided`, a file uploaded at the background question is marked background automatically. Send a photo as a file when you want Telegram to preserve its original resolution. Conversational reading includes the first 12,000 extracted characters per file read and reports shortening; the outreach workflow retains its separate excerpt limits described below.

**In the dashboard:** open **New run**, choose a file purpose, and add files under **Files for this goal**. Each file has its own purpose selector, status, and **Inspect text** button. Wait for `ready` and inspect the extracted words before starting. Use **Retry file** for a failed read. A run started while extraction is queued waits behind that extraction job; if extraction fails, fix/retry the file and then retry the run.

| Purpose | How the agent uses it |
|---|---|
| **My background** | Your experience or offering: used to interpret your goal and personalize messages. Kept out of the prospect research evidence. |
| **Research evidence** | Facts and sources about potential targets: used with notes, search results, and public pages to find relevant prospects. |

Supported formats:

- **PDF:** reads selectable text. Pages without selectable text are rendered and read with OCR.
- **Images:** PNG, JPEG, WebP, TIFF, and BMP; OCR reads printed text.
- **Documents:** DOCX and ODT main text. Embedded pictures, comments, headers/footers, and exact page layout are not extracted.
- **Text:** TXT, Markdown, CSV, JSON, YAML, XML, LOG, RST, TEX, and HTML/HTM; UTF-8 or UTF-16. HTML scripts and styles are omitted. CSV/JSON/XML are read as text, not executed or interpreted as instructions.

**OCR** means optical character recognition: converting image text into words. Install Tesseract for images and scanned PDFs:

```bash
# macOS
brew install tesseract

# Debian/Ubuntu
sudo apt-get update
sudo apt-get install tesseract-ocr tesseract-ocr-eng
```

The Docker image includes English OCR. For other languages, install the corresponding Tesseract language data and set `OUTREACH_OCR_LANGUAGES`, for example `eng+hin` when both are installed. `tesseract --list-langs` lists installed languages. Connections shows whether the OCR executable is available; extraction verifies that the chosen language data works. [Tesseract usage and language options](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html).

There is no separate OCR API key or paid extraction call. Uploading only queues local reading. Starting a run sends relevant extracted text to your configured Groq/OpenAI model; selected topics can become Brave search queries when search is enabled. File text is evidence and cannot change approval or sending rules.

Limits: **five files per run, 10 MiB per file, 20 PDF pages/image frames per file, 16 megapixels per input image, and 40,000 extracted characters per file**. A file reader runs for at most 90 seconds, with 20 seconds per OCR page. Interpretation uses excerpts of up to 20,000 text characters across files; background joins the 10,000-character sender context. Research combines bounded file excerpts and notes, leaving room for web evidence. Shortening produces visible notices. Text/office files use “page 1” as a source section; it is not a Word layout page number.

OCR can misread names and addresses. Inspect extracted text; this reader does not interpret diagrams, photographs, or handwriting reliably. Password-protected PDFs, legacy `.doc`, spreadsheets, archives, and arbitrary binary files are unsupported. PDFs mixing selectable text and scanned areas use their text layer; export image-only pages separately if needed.

Filename/page citations remain attached to research evidence. Email addresses found in an uploaded file always require your selection before outreach; supplied recipient addresses still take precedence. Files stay in the local data directory across restarts. **Remove** and `/clearfiles` detach references from the new goal; they do not delete originals or historical evidence.

## 4. Connect Gmail

**OAuth** is Google's sign-in process for granting this application access to your Gmail account. The connector is implemented, but Gmail is only connected after the steps below finish and Connections shows your email address.

1. Open [Google Cloud Console](https://console.cloud.google.com/). Create or select a project, for example **Outreach Agent**. In **APIs & Services → Library**, find **Gmail API** and enable it. [Google's setup instructions](https://developers.google.com/workspace/gmail/api/quickstart/python#enable_the_api).
2. Open **Google Auth platform → Branding**. If prompted, click **Get started** and enter the app name, support email, and contact email. For your personal Gmail account, choose **External** as the audience. Keep the app in Testing and add your Gmail address under **Audience → Test users**. [Consent setup](https://developers.google.com/workspace/guides/configure-oauth-consent).
3. In **Data Access**, add `https://www.googleapis.com/auth/gmail.readonly` and `https://www.googleapis.com/auth/gmail.compose`. Save the scope selection. These are the two permissions requested by this project's connector.
4. Open **Clients → Create client**, select **Web application**, and name it **Outreach Local**. In **Authorized redirect URIs**, enter the exact callback below. Leave JavaScript origins empty; the Python server handles the sign-in. Create the client and copy its client ID and client secret. [Google's web-client instructions](https://developers.google.com/identity/protocols/oauth2/web-server#creatingcred).

```text
http://127.0.0.1:8000/api/connectors/gmail/callback
```

5. Edit `.env` in the project folder, beside `README.md`. Set the following values. Use your Google client credentials, not your Gmail password. Keep the existing `OUTREACH_SECRET_KEY`; generate it using section 2 only if it is missing. Leave real credentials out of `.env.example`.

```dotenv
OUTREACH_GOOGLE_CLIENT_ID=your_client_id.apps.googleusercontent.com
OUTREACH_GOOGLE_CLIENT_SECRET=your_client_secret
OUTREACH_APP_URL=http://127.0.0.1:8000
OUTREACH_READ_GMAIL=true
OUTREACH_ENABLE_SENDING=false
```

6. Restart with `python -m app.main` from the project folder. Use the normal service command for your account connection; demo mode uses fake Gmail. Open **http://127.0.0.1:8000**, enter your `OUTREACH_OWNER_PASSWORD`, open **Connections**, and select **Connect Google**. Sign in to the account you added as a test user and grant the requested permissions. Connections should then show that Gmail address. Telegram's `/account` command shows the same account.

For `redirect_uri_mismatch`, compare the full callback above with the registered URI: scheme, hostname, port, path, and trailing slash must match. A test-user access error usually means the selected Gmail account is missing from **Audience → Test users**, or the wrong Cloud project/client was configured. Both client values and the local encryption key must be present before **Connect Google** can work.

The app requests `gmail.readonly` to read history and `gmail.compose` to manage drafts and send approved messages. Compose permission includes sending, but this application still enforces the server sending switch, requested action, and exact-message approval. [Gmail permission definitions](https://developers.google.com/workspace/gmail/api/auth/scopes).

Access tokens renew automatically using the encrypted refresh token. Google can revoke or expire authorization; external apps in Testing generally receive seven-day refresh tokens for these scopes. Reconnect when shown in Connections. [Google token expiration rules](https://developers.google.com/identity/protocols/oauth2#expiration).

There is no need to manually populate `GMAIL_ACCESS_TOKEN` for this service. Existing local values are left intact but are not used by the connected-account runtime.

Verify your address on Connections. First approve a draft addressed to yourself and inspect it in Gmail. For a live send test, explicitly set `OUTREACH_ENABLE_SENDING=true`, restart, create a **new send-mode run addressed to yourself**, and approve its exact message. An earlier draft-mode approval never authorizes a send. Switching Google accounts blocks pending actions bound to the earlier account; reconnecting the same account without disconnecting preserves its identity.

**Check replies** reads tracked conversations on demand, processing at most five new inbound messages and scanning at most 20 tracked actions per request. A saved position rotates through larger histories. It saves reply classification and supported memory; it does not send follow-ups. Only plain-text email bodies are extracted in this version.

## 5. Storage, limits, and recovery

Leave these defaults for local operation:

```dotenv
OUTREACH_DATA_DIR=.data
OUTREACH_DATABASE_URL=
OUTREACH_CHECKPOINT_BACKEND=sqlite
OUTREACH_CHECKPOINT_POSTGRES_URL=
```

Both databases use **SQLite**. `relationships.sqlite3` contains runs, jobs, contacts, events, decisions, and encrypted credentials. `checkpoints.sqlite3` contains LangGraph progress. PostgreSQL is an optional retained adapter, not required or used alongside these defaults. The packaged one-worker service is validated with SQLite.

Migrations apply automatically on startup. Uploaded originals live in `uploads/`, and extracted text/metadata live in the application database. Back up the entire data directory with the service stopped and retain the encryption key separately. Do not delete SQLite journal/WAL files from a running service. Use the same directory after restart; approvals and queued work remain available. Interrupted executions require **Retry**. An uncertain Gmail write remains blocked: inspect Gmail and the recorded outcome before attempting any manual recovery.

**Pause queue** prevents new jobs from starting; it does not interrupt the active job. **Cancel run** stops further work at a safe boundary. If Gmail is already creating/sending a message, the application records that result before stopping.

Defaults: five pages per run, 20 seconds per page, one linked-page level, 15,000 extracted characters per page, two searches, at most ten discovered/five qualified prospects, and one shared revision. Model calls and browser attempts stay counted across retries.

The default model budget reserves `$0.05` per call up to `$2` per run; it is **an estimate, not actual pricing**. A smaller starting cap can be configured without changing code:

```dotenv
OUTREACH_LIMITS_JSON={"max_estimated_cost_per_run":0.50,"max_model_calls":10}
```

A run needing more calls stops at the cap. Changing limits requires restarting. Search/browser usage counts are shown separately; their costs are not included in the model estimate. Reported token counts appear when the provider returns them.

## 6. Validate locally

```bash
python -m pytest
RUN_BROWSER_TESTS=1 RUN_OCR_TESTS=1 python -m pytest
python -m evals.run --output .data/evaluations.json
```

The second command needs Chromium and Tesseract; it includes real local browser, image OCR, and scanned-PDF checks. Both commands use fictional files and need no external-service credentials. Live model evaluations are an explicit separate choice: export your model environment settings and run `python -m evals.run --live`. That evaluation command does not load `.env` and consumes model credits.

Use `/health` for basic service health and Connections for connector status. The current service intentionally has no public `/docs` or legacy `/outreach` route; the [API guide](API_GUIDE.md) documents its authenticated interface.

## 7. Docker packaging

After local checks, Docker Compose can package the same service:

```bash
docker compose up --build -d
docker compose logs -f outreach
docker compose down
```

Compose reads `.env`, binds port 8000 to localhost, and saves SQLite data in the `outreach_data` named volume. `down` retains that volume; do not use `down -v` when keeping data. Container storage is separate from your host `.data` unless you deliberately migrate it with both services stopped.

The image runs as a non-root user with sandboxed Chromium. Compose supplies the upstream Playwright seccomp profile, an init process, and 1 GB shared memory. The host must support unprivileged user namespaces; do not disable Chromium’s sandbox to work around a hosting restriction. [Playwright container requirements](https://playwright.dev/python/docs/docker).

For eventual remote hosting, put the service behind an HTTPS reverse proxy, set `OUTREACH_APP_URL` to that exact origin, and register its Google callback. Keep one instance and persistent local storage. Remote deployment and real Google/Telegram checks are not performed by the local demo; see [validation](VALIDATION.md).
