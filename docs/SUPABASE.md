# Save application state in Supabase

Supabase hosts a PostgreSQL database. For this app, **one database** holds conversations, jobs, research, email drafts, outcomes, encrypted Gmail credentials, and LangGraph checkpoints. A checkpoint is saved workflow progress that lets the same run continue after a pause or restart.

Supabase support is implemented and tested against a temporary local PostgreSQL server. Your cloud database is connected only after you create a project, add its URL, and start the app successfully. Until then, the existing SQLite files remain active.

## Create your project

1. Sign in at [Supabase](https://supabase.com/dashboard) and select **New project**. Choose your organization, enter a project name, choose a nearby region, and set a strong database password. Save that password privately. Wait for the database to finish starting.
2. Open the project's **Connect** panel. Choose the **Session pooler** PostgreSQL connection string, using port **5432**. This works from IPv4 networks. Copy the exact hostname and username shown; do not construct them yourself. A direct connection also works if your network supports its address.
3. Replace the password placeholder locally. If your password has characters such as `@`, `/`, `#`, or `:`, use their percent-encoded form in the URL. Keep the full connection string out of chat, screenshots, and Git.

Use the session pooler, not the transaction pooler on port 6543: this service keeps database sessions open for workflow checkpoints and its single-worker lock. See [Supabase's connection guide](https://supabase.com/docs/guides/database/connecting-to-postgres).

## Configure this application

Stop the current service with **Ctrl+C**. From the project folder:

```bash
source .venv/bin/activate
python -m pip install -e '.[dev,postgres]'
```

In your existing `.env`, fill in this one setting with the copied URL:

```dotenv
OUTREACH_SUPABASE_DATABASE_URL=postgresql://postgres.PROJECT_REF:ENCODED_PASSWORD@COPIED_POOLER_HOST:5432/postgres?sslmode=require
```

The line above is a placeholder, not a working address. Use the values from **Connect**. Leave `OUTREACH_DATABASE_URL` and `OUTREACH_CHECKPOINT_POSTGRES_URL` empty. You can leave `OUTREACH_CHECKPOINT_BACKEND=sqlite` in the template: a nonempty Supabase URL selects Postgres for both stores automatically. No Supabase publishable, anonymous, or service-role API key is needed; Python connects directly to the database.

Keep `OUTREACH_DATA_DIR=.data`: uploaded originals and the local process lock still use it. Keep your existing `OUTREACH_SECRET_KEY` and all other credentials. Supabase stores encrypted Google credentials; their encryption key remains in your environment. This integration uses Supabase **Database**, not Supabase Auth or file Storage.

```bash
python -m app.main
```

Startup applies the existing database migrations and creates the checkpoint tables. You do not need to paste SQL into the dashboard. If startup cannot connect, check the project status, copied URL, database password, and network access. It fails rather than quietly saving to a different database. SSL encryption is required for remote connections; `sslmode=verify-full` with Supabase's certificate in `sslrootcert` additionally verifies the server's identity.

## Confirm where state is saved

- Open the app dashboard → **Connections → Saved state**. It should show `supabase` and `postgres` checkpoints.
- In Supabase's Table Editor, select the **outreach** schema. A schema is a named group of tables. You should see application tables and LangGraph tables such as `checkpoints`.
- Ordinary Telegram conversation should save a chat job and history. A requested outreach run saves its goal, sources, drafts, progress, and outcomes. Restarting keeps those records; interrupted execution requires an explicit retry.

The `outreach` schema stays outside the public Data API. Row-level security is enabled, and browser-facing roles receive no access. The authenticated Python server connects as the table owner. Do not add `outreach` to the exposed schemas or put the database URL in browser JavaScript. [Supabase Data API security](https://supabase.com/docs/guides/api/securing-your-api).

## Existing local records and backups

Switching from SQLite starts using a separate store; **this change does not copy existing local records into Supabase**. Finish pending local work and back up `.data` with the service stopped before switching. The original SQLite files are preserved. Gmail credentials in SQLite are not copied either: reconnect Gmail through the dashboard after the switch.

Do not alternate stores while jobs or Gmail writes are pending: each has its own action history and duplicate protection. To keep old runs active in Supabase, plan a data migration before switching. Uploaded originals remain local and still need a backup; back up the hosted database separately and retain the encryption key privately.

## Requested email drafts

Research and file reading do not start drafting. Ask explicitly, for example: **“Create outreach email drafts for these companies and keep them in Gmail.”** Check the proposal, press **Start outreach**, and resolve any missing recipient addresses. After contact checks and automated review pass, the agent saves drafts and tells you where to find them. Review, edit, and send them yourself in Gmail.

The current default is **up to five qualified prospects per run**, subject to evidence and budget. For ten emails, request smaller batches or deliberately change the operating limits after reviewing the cost. The app does not raise limits automatically or guarantee enough suitable recipients. The former sending flag cannot enable agent sending. Manual Gmail sends are not automatically reconciled into the dashboard's historical agent-send counter.
