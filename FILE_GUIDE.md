# File guide

This application is being reorganized around one outreach agent, Telegram, and a dashboard. This guide describes completed changes; the active [plan](plan.md) lists the remaining work. The [earlier phase history](docs/PHASE_HISTORY.md) and [earlier file explanations](docs/FILE_GUIDE_HISTORY.md) preserve the learning record.

## Phase 31: Consolidate the agent

The old interactive CLI and separate research-only workflow were removed. The complete LangGraph workflow now lives under `app/agent`. The working research, qualification, memory, contact rules, writing, review, human approval, and Gmail protections were reused. Model providers now live separately from the records they produce. All 285 retained tests passed after the move; removed checks covered retired CLI/research-only entry points. The temporary complete-workflow HTTP routes are replaced by authenticated background-job routes in the connector steps below.

## How the code is organized

| Location | Purpose and connections |
|---|---|
| `app/agent/graph.py` | Builds the complete workflow from nodes, which are individual steps. `build_full_graph(checkpointer)` returns a runnable graph whose progress can be saved. Research and writing use smaller internal graphs. |
| `app/agent/state.py` | Defines the basic collections for one run; the complete state in `app/domain/workflow.py` adds sender, recipients, approvals, outcomes, and progress. Each run owns separate collections. |
| `app/agent/nodes/` | Connects domain components to graph state. Each node takes the current state and services, and returns only the fields it changed. |
| `app/agent/components/` | Implements interpretation, research, qualification, strategy, writing, review, and relationship-memory extraction/retrieval. Model responses must match domain records and available evidence. |
| `app/agent/prompts/` | Contains the model instructions used by those components. |
| `app/agent/policy.py` | `check_contact` returns whether a recipient can be contacted and why. `message_fingerprint` identifies the exact approved sender, recipient, and message. |
| `app/agent/routing.py` | Small functions choose the next graph step based on qualification, review, and human decisions. |
| `app/agent/context.py` | Supplies per-run services. Managed model and search clients reserve budgets before calls and record usage/events. |
| `app/agent/replies.py` | Classifies an incoming reply and saves sourced relationship facts. Explicit opt-outs block further contact. |
| `app/domain/` | Validated Python records for goals, prospects, drafts, decisions, replies, and saved workflow state. A record is a checked format for exchanging information. |
| `app/llm/` | Groq, OpenAI, fake clients, and optional measured routing. `generate_structured` validates returned data against the requested record. |
| `app/connectors/search.py` | Brave and fake search adapters. A search returns titles, URLs, and snippets. |
| `app/connectors/gmail/client.py` | Reads threads and creates/sends messages through Gmail, with a fake client for tests. External writes are authorized by the workflow before this adapter is called. |
| `app/services/runs.py` | `RunManager` starts, reads, resumes, and retries saved graph executions. A run ID links graph checkpoints to application records. |
| `app/services/runtime.py` | Opens database, checkpoints, and network clients together and closes them when the service stops. |
| `app/services/limits.py` | Defines bounds on calls, timeouts, revisions, and estimated spending. Estimated spending is not the provider's actual bill. |
| `app/storage/` | SQL tables, relationship repositories, execution events, and checkpoint connections. Relationship records and LangGraph checkpoints retain their separate SQLite files. |
| `app/settings.py` | Reads configuration without making external calls. |
| `tests/` | Tests components and complete flows with local service substitutes. No real account credentials are required. |
| `evals/` | Four fictional scenarios and their scoring rules. Simulated evaluations exercise the workflow; explicitly selected live evaluation measures a configured model. |

Further connector, dashboard, migration, and setup explanations are added below with their implementation.
