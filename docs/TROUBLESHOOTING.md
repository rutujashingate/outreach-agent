# Troubleshooting

Start with **Connections**, then open the affected run's events and saved job result. Keep keys and provider responses out of shared screenshots.

| Symptom | Check / action |
|---|---|
| Bot is silent | Confirm the service is running, your numeric owner ID is correct, and `/health` reports all Telegram components active. Use one instance per bot. |
| Old configuration still appears | Stop with **Ctrl+C**, save `.env`, then restart. Exported environment values take precedence; duplicate settings can override one another. |
| Model access denied | Check the selected provider's key, model/endpoint permissions, credits, and spending limit. “Configured” only means a key is present. |
| Groq says a model is blocked | Inspect organization/project model permissions in [Groq Console](https://console.groq.com/). Another key in the same organization does not bypass the block. |
| Search fails | Keyless public search may be rate-limited. Try later, narrow the query, or supply a public URL. Brave is optional. |
| Browser cannot read a page | Confirm Chromium is installed and available. Private/local URLs, login actions, forms, and downloads are blocked. |
| Google redirect mismatch | The registered callback must exactly match `OUTREACH_APP_URL` plus `/api/connectors/gmail/callback`, including hostname and port. |
| Google denies sign-in | Check your test-user address and selected Cloud project/client. Tokens can expire or be revoked; reconnect from **Connections**. |
| Gmail update is blocked | The draft/account may have changed since the preview. Inspect Gmail and request a fresh edit. A lost write confirmation must be inspected before another attempt. |
| File remains queued | Resume the queue. For extraction failures, inspect `/files` or **Inspect text**, resolve OCR/format issues, and retry the file. |
| Several unfinished tasks | Use `/continue RUN_ID` to choose one. **Continue** never supplies an approval. |
| Usage limit reached | Inspect calls/usage. Limits remain spent across retries; narrow the work or deliberately change limits and restart. |

## Budget and recovery

The default reserved model budget counts **$0.05 per attempted call**, up to **$2/run**. This is an application estimate, not provider pricing or a guaranteed billing cap. Failed calls count too. Provider billing is separate.

A smaller run allowance can be set in `.env`:

```dotenv
OUTREACH_LIMITS_JSON={"max_estimated_cost_per_run":0.50,"max_model_calls":10}
```

It may stop complex work sooner. Restart after changing limits.

**Pause queue** prevents new jobs from starting. **Stop** saves a resumable boundary. **Cancel** ends the run; an external action already underway records its result first. Uncertain Gmail actions are never automatically replayed.

## Protect saved data

Keep `OUTREACH_SECRET_KEY`; replacing it makes encrypted Gmail tokens unreadable. Back up local data with the service stopped, and back up hosted database records and file originals separately. Changing storage backends does not automatically copy prior runs or credentials. See [storage setup](SUPABASE.md).

HTML-only drafts and oversized messages require editing in Gmail. OCR reads printed text; photographs, handwriting, and diagrams may not extract meaningfully. [Setup](SETUP.md#read-files-and-use-them-for-research) lists supported formats and limits.

[Setup](SETUP.md) · [Models and tools](MODELS_AND_TOOLS.md) · [Validation](VALIDATION.md)
