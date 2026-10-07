# Local validation — October 7, 2026

The connected application is implemented and its local flow is verified. The checks below distinguish real local execution from simulated external services.

| Check | Result |
|---|---|
| Existing behavior after moving the core | 285 retained tests passed; tests for removed CLI/research-only entry points were retired. |
| Final automated suite | **327 passed** with `RUN_BROWSER_TESTS=1 python -m pytest -o addopts='' -q`. Includes actual Chromium against a local fixture; no external-service credentials or public API calls. |
| Simulated evaluations | All four scenarios—academic, jobs, sales, networking—completed. Each used six scripted model calls and passed the reference scoring checks. This does not measure a live model’s quality. |
| Telegram-to-Gmail flow | Fake Telegram drove the real service/graph through goal → fake browser evidence → qualification/contact checks → draft/review → approval → one fake Gmail draft. The dashboard service submitted Telegram’s saved choice; stale buttons did not repeat the action. |
| Browser network restrictions | Real Chromium rendered JavaScript from a local fixture and blocked POST requests, private destinations, and a private redirect. Unit checks also cover mixed DNS answers and persistent limits. |
| Public-page smoke check | `BrowserClient` successfully read `https://example.com` with the production public-network proxy and sandboxed Chromium. |
| Dashboard walkthrough | Real Chromium exercised login, new research, recipient evidence, automated review, approval, fake Gmail drafting, saved message inspection, overview, Connections, and reply checking. Desktop and 390-pixel mobile layouts were inspected; no JavaScript errors or mobile horizontal overflow. |
| Gmail OAuth behavior | Mocked tests passed for encrypted storage, renewal, revoked access, required scopes, session-bound one-use state, verified email, same-account reconnect, changed-account blocking, and disconnect cleanup. |
| Restart and duplicate protection | A packaged service was stopped at approval, restarted, and approved through HTTP. It retained the pending draft, kept the original six model calls, returned the original job for a repeated request, and recorded one fake Gmail draft. |
| Cancellation and queue controls | Tests passed for queue pause, cancellation before another node, and recording an external action already underway. All prospects must have a decision before a batch resumes. |
| Data preservation and instance lock | Migration tests adopted earlier contact tables without losing opt-outs. A second instance using the same data directory was rejected. Interrupted claimed jobs required explicit retry. |
| Clean installation and packaging | Installed into a fresh Python 3.12 environment. Built and installed a wheel; started it from outside the repository. Dashboard assets, migrations, authentication, health, research, and saved approval worked. |
| Documentation/assets | Updated file guide, setup/API instructions, current plan, and Mermaid/SVG diagram. JavaScript syntax, Python compilation, and Git whitespace checks passed. |

Existing local `.env` credentials and database files were preserved. Manual service checks used isolated temporary data directories and simulated Gmail/model/search/Telegram clients.

## Checks that still need the owner's environment

- **Real Telegram delivery:** configure the bot token and owner ID, then complete the guided conversation in your private chat.
- **Real Google connection and actions:** configure the Google web client and encryption key, complete consent, create an approved draft addressed to yourself, then explicitly enable and approve a separate test send to yourself. No real Gmail draft or email was created during this implementation.
- **Live Groq quality:** provide your model key and review real sourced results. The simulated eval scores are not live model benchmarks.
- **Docker build/run and Linux hosting:** Docker is not installed on the development machine. Dockerfile/Compose packaging is provided, but a container build and host-specific Chromium sandbox operation have not been verified. Remote hosting has not been performed.

Follow [setup](SETUP.md) for these checks. Local implementation is complete; live connector acceptance remains separate until the configured accounts and hosting environment are exercised.
