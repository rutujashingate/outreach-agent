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

4. Put **your** number in `OUTREACH_TELEGRAM_OWNER_ID`. Start the service with `python -m app.main` and send `/new` to your bot.

This application uses long polling, so it needs no public Telegram webhook. If the bot already has a webhook, remove that old configuration first; the connector reports a configuration error instead of silently replacing it. Use one running service per bot and data directory.

The conversation asks for your goal, background, research mode, known addresses, and action. `-` reuses the saved sender profile or indicates no supplied recipients where prompted. Start in **draft** mode. Use the dashboard’s Connections page to save your name and accurate background before live outreach.

| Command | Result |
|---|---|
| `/new` | Guided new request. |
| `/runs`, `/status RUN_ID` | Recent runs or current progress. |
| `/review RUN_ID` | Current draft cards with approve/reject/edit choices. |
| `/recipients RUN_ID` | Resolve missing or ambiguous recipient addresses. |
| `/retry RUN_ID`, `/cancel RUN_ID` | Retry failed work or request a stop at the next safe boundary. |
| `/replies` | Queue a reply check for tracked Gmail conversations. |
| `/account`, `/help` | Gmail connection status or command help. |

Choose a decision for every pending prospect and submit the batch. Decisions made in the dashboard are immediately authoritative in Telegram too. Old buttons cannot approve a changed message. If Telegram delivery is uncertain, `/review` or `/status` retrieves current saved information.

## 4. Connect Gmail

In your [Google Cloud project](https://console.cloud.google.com/), enable the Gmail API, configure the OAuth consent screen, and add your account as a test user if the app is in Testing. Create an OAuth client of type **Web application**. Register this exact authorized redirect URI:

```text
http://127.0.0.1:8000/api/connectors/gmail/callback
```

Save its client ID and secret in `.env`, along with the encryption key. Start the application, sign in at the same `127.0.0.1` address, open **Connections**, and select **Connect Google**. Complete consent in the same browser. Google requires the redirect URI to match the registered value. [Google web-server OAuth setup](https://developers.google.com/identity/protocols/oauth2/web-server).

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

Migrations apply automatically on startup. Back up the data directory with the service stopped and retain the encryption key separately. Do not delete SQLite journal/WAL files from a running service. Use the same directory after restart; approvals and queued work remain available. Interrupted executions require **Retry**. An uncertain Gmail write remains blocked: inspect Gmail and the recorded outcome before attempting any manual recovery.

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
RUN_BROWSER_TESTS=1 python -m pytest
python -m evals.run --output .data/evaluations.json
```

The second command needs Chromium and includes a local browser fixture. Neither command requires real service credentials. Live model evaluations are an explicit separate choice: export your model environment settings and run `python -m evals.run --live`. That evaluation command does not load `.env` and consumes model credits.

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
