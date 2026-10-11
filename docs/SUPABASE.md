# Supabase, private files, and semantic search

Supabase hosts the application's PostgreSQL database and private original-file bucket. **pgvector is an extension inside that database**, used to search text by meaning. The Python service still runs Telegram, LangGraph, tools, and the dashboard.

The integration is implemented. Your hosted resources are connected only after you add credentials and complete setup. Until then, the default is local SQLite and local files.

## 1. Create the project and keep credentials private

Create a project in [Supabase](https://supabase.com/dashboard), choose a nearby region, and save its database password privately. Wait for the database to start. You do not need to create tables or a bucket manually.

Find these three values:

| Local setting | Where to find it | Purpose |
|---|---|---|
| `OUTREACH_SUPABASE_DATABASE_URL` | **Connect → Direct — Connection string → Session pooler**, port **5432** | One SQL connection string for application records and LangGraph checkpoints. Replace the password placeholder locally. |
| `OUTREACH_SUPABASE_URL` | Project **Connect** panel or API settings | Project HTTPS address, such as `https://PROJECT_REF.supabase.co`. |
| `OUTREACH_SUPABASE_SECRET_KEY` | **Settings → API Keys → Secret keys** | Server-only `sb_secret_…` key for managing private originals. |

Paste real values only into `.env`, never chat or `.env.example`. The Supabase secret key is different from `OUTREACH_SECRET_KEY`, which encrypts Gmail credentials. Retain your existing Gmail encryption key.

The **Framework** tab shows the HTTPS project URL. Select **Direct — Connection string** to find the PostgreSQL URL, which starts with `postgresql://`. Choose the **Session pooler** method inside that tab and copy its exact hostname and username. A direct PostgreSQL connection also works when your network supports its address; session pooling is the recommended choice for IPv4 compatibility.

Password characters such as `@`, `/`, `#`, and `:` need percent encoding inside the connection string. For example, a literal `@` in the password becomes `%40`; keep the `@` separating the password from the database hostname unchanged. Encode only the password portion, without changing your actual database password. Remote SQL connections require SSL. Direct and session connections retain the schema selection and advisory lock used by this application; transaction mode on port 6543 is unsupported. [Connection documentation](https://supabase.com/docs/guides/database/connecting-to-postgres).

## 2. Install and provision

Stop the service with **Ctrl+C**. From the project folder:

```bash
source .venv/bin/activate
python -m pip install -e '.[dev,postgres,semantic]'
```

After filling the three credentials, set:

```dotenv
OUTREACH_DOCUMENT_STORAGE=supabase
OUTREACH_SEMANTIC_SEARCH_ENABLED=true
```

Run:

```bash
python -m app.setup_storage --download-model --fresh-start
```

This command:

1. Downloads the English `BAAI/bge-small-en-v1.5` model into `.data/models` for local CPU embeddings. No Hugging Face API key is required; its unauthenticated-download warning can be ignored for this public model.
2. Backs up existing SQLite files and uploaded originals under `.data/backups`, leaving the originals intact. The fresh start preserves Telegram's acknowledged-update cursor but does not import old test runs or account tokens.
3. Applies versioned database migrations, creates application tables in the private `outreach` schema, and enables pgvector in `extensions`. LangGraph creates its checkpoint tables in the same private schema.
4. Creates the private `outreach-documents` bucket and checks its visibility and 10 MiB file limit.
5. Tests database/checkpoint persistence, private original-file storage, embeddings, retrieval, and cleanup. No Grok, Telegram-send, or Gmail calls occur.

A self-hosted PostgreSQL server needs the pgvector extension installed first. Supabase supplies it. The app connects as the database/table owner; ordinary Data API roles have no access to `outreach`. Keep that schema outside Supabase's exposed Data API schemas. Storage uses the server secret key, so all file authorization happens in the authenticated Python service.

For later setup checks, omit `--fresh-start`:

```bash
python -m app.setup_storage
python -m app.main
```

Setup is repeatable and does not erase existing cloud data. `--fresh-start` refuses a cloud database that already has runs. Reconnect Gmail from the dashboard after the fresh switch. Do not switch between local and cloud action histories while work is pending.

## 3. Use the saved library

Send a document in Telegram or upload one through the dashboard's **New run** form. The service stores its original, extracts text, then queues indexing. Website text actually read by the browser also becomes saved evidence. Search-result snippets and generated model claims are not automatically indexed as source pages.

The embedding model turns text into 384 numbers that represent its meaning. pgvector compares those numbers; PostgreSQL keyword search also contributes to the ranking. Documents are split within page boundaries into approximately 300-token passages with 50-token overlap. Indexing uses the existing worker, and CPU inference runs in background threads.

Ask **“Find my earlier experience with API monitoring”** in a later conversation. The agent can choose `search_saved`, retrieve up to five passages, and answer with source references and dates. Saved documents default to background; explicitly attached files retain the role you choose for the current task. Personal background is excluded from prospect-research material.

In **Saved knowledge**, search directly, inspect the returned text and citations, open a document, download its original, or reindex a failed source. Indexing failures retain the previous published passages. Unchanged evidence reuses existing vectors. Reindex after deliberately changing the configured embedding implementation/version; incompatible vectors are excluded from semantic matching.

If the local model cannot load, search clearly reports **keyword-only** results. It never silently selects a paid embedding provider. English is the supported retrieval language for this initial model. Image and scanned-PDF search uses OCR-extracted text, not visual-image embeddings. Historical website passages may be out of date; ask for current web research when freshness matters.

## 4. Validate storage and continuation

In **Connections → Storage validation**, click **Validate storage**. The shared worker runs isolated write/read checks and removes its temporary records, checkpoint, and object. Reports show each check's result, elapsed time, and safe error. A paused queue must be resumed before checks can run. The endpoint is `POST /api/storage/validate`; the latest report appears in connector status.

For restart recovery, run a separate check: start a task, say **stop**, restart the service, and say **continue**. The same task should retain its original instructions, evidence, completed steps, budgets, and next step. Checkpoints handle this; vector search helps find relevant content across tasks. Neither mechanism bypasses pending recipient or review decisions.

Run retrieval quality checks after the model download:

```bash
python -m evals.retrieval --output .data/retrieval-evaluation.json
```

This compares real local hybrid retrieval with keyword-only retrieval on a small English fixture. It reports recall among the first five results and mean reciprocal rank (how near the top the expected passage appears). It does not measure generated-answer accuracy.

Keep `.data/models` mounted on a future server to reuse the model cache. Keep database backups, private-bucket originals, and the Gmail encryption key; a database backup alone does not include original file bytes. The application never automatically deletes your saved library.

## Requested emails

File reading, saved search, and web research do not create emails. Explicitly request drafts to start preparation. Ask to see a plan first if you want it to wait. Existing-draft edits show a preview and require **Approve changes** before updating the same Gmail draft. The default is up to five qualified prospects per run, subject to evidence and budget. Requested Gmail drafts are saved after automated review; you review, edit, and click **Send** manually in Gmail. The agent cannot send messages.
