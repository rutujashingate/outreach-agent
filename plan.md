# Outreach Agent Plan

Phase one builds the application foundation. Phase two gives workflow results a consistent format. Both phases are implemented; their work and verification are recorded below.

## What we want to achieve

Build a small application that accepts an outreach goal, checks that the input is valid, creates a separate record for the request, and returns that record to the user.

For example, a user could submit:

> Find AI startups that may need our API observability product.

The application will return the same goal, empty collections for future results, and a status confirming that the application foundation is working.

Phase one establishes the path that later research, qualification, and email-writing steps will follow.

## What we will build

1. **Set up the Python project.**

   Create the application folders, a place for tests, and a file listing the required software packages.

   Use Python 3.12 or newer. FastAPI will handle incoming requests, Pydantic 2 will check the data, Uvicorn will run the application, and pytest will run the tests. HTTPX will support testing the API.

   The project should install into its own Python environment so its packages are separate from other projects on the computer.

2. **Create the entry point for an outreach request.**

   Provide an endpoint called `POST /outreach`. This is the address another application or a developer can use to submit a goal.

   Each request must contain one field, `goal`, holding the user's instructions as text.

   Remove spaces at the beginning and end while preserving the wording and capitalization. Accept goals between 1 and 2,000 characters after trimming.

   Reject missing goals, blank text, values that are not text, and unexpected fields. Invalid requests should receive the standard validation response with status `422`.

3. **Create a separate record for each request.**

   This record is called `OutreachState`. It holds the goal and the results collected as the workflow progresses.

   At the start, it contains the user's goal, empty lists of discovered and qualified prospects, empty collections for strategies, email drafts, and reviews, and a progress value of `"initialized"`.

   Each request must have its own collections. Adding information to one request must never change another request.

   These records live in application memory during the request. Saving them in a database belongs to a later phase.

4. **Add the workflow coordinator.**

   The workflow coordinator is the function that will eventually call the research, qualification, and writing components in order.

   For phase one, it receives the request's record, keeps its contents intact, changes the progress value to `"skeleton_ready"`, and returns the record.

   Keep this coordination in `workflow.py`. The API's responsibility is to receive the request and return the result.

5. **Connect the complete request path.**

   When a valid request arrives, the application checks the goal, creates a fresh record, passes it through the coordinator, and returns the result.

   A successful response has status `200` and contains these fields: `goal`, `prospects`, `qualified_prospects`, `strategies`, `drafts`, `reviews`, and `current_step`.

   The goal matches the accepted input, the result collections are empty, and `current_step` is `"skeleton_ready"`.

   The endpoint and its expected inputs and outputs also appear in the application's automatically generated API documentation.

6. **Write clear setup instructions.**

   Add a README explaining how to install the project, start it, submit an example goal, and run the tests.

   Explain that `"skeleton_ready"` means the request successfully passed through the application foundation.

   Finish by following the README from a fresh Python environment to confirm that the instructions work.

## Project structure

```text
app/
├── __init__.py
├── main.py
├── api/
│   ├── __init__.py
│   └── outreach.py
├── orchestration/
│   ├── __init__.py
│   ├── state.py
│   └── workflow.py
└── models/
    ├── __init__.py
    └── schemas.py

tests/
├── conftest.py
├── test_schemas.py
├── test_state.py
├── test_workflow.py
└── test_outreach_api.py

pyproject.toml
.gitignore
README.md
plan.md
```

## How we will check it

Automated tests verify that:

- A valid goal is accepted and returned correctly.
- Spaces at the beginning and end are removed.
- Missing, blank, incorrectly typed, and unexpected inputs are rejected.
- A 2,000-character goal is accepted; a 2,001-character goal is rejected.
- New records start with empty collections and the expected progress value.
- Changing one record leaves another record unchanged.
- The coordinator preserves the record's contents and updates its progress.
- Valid API requests reach the coordinator; invalid requests stop before it.
- The API returns the coordinator's result in the expected format.
- The endpoint's input and output formats are visible in the API documentation.

The tests run without external-service credentials or calls to external APIs.

A final manual check starts the application, submits an example goal through `POST /outreach`, confirms the response, and checks that the API documentation at `/docs` is available.

## Completion criteria and verification

- [x] A fresh environment can install and start the application using the README.
- [x] `POST /outreach` accepts a valid goal and returns the documented state.
- [x] Invalid requests produce validation errors before workflow execution.
- [x] Requests have independent state.
- [x] The workflow returns `"skeleton_ready"` with empty result collections.
- [x] All 44 automated tests pass without external API calls.
- [x] The application runs without external-service credentials.
- [x] The live API returns `200` for a valid goal and `422` for a blank goal; `/docs` returns `200`.

Verified in a fresh Python 3.12.9 environment. The dependency check found no conflicts. The temporary development server was stopped after verification.

## Boundaries and decisions

This plan uses the numbered **"Skeleton + State"** phase from the architecture. The larger research-and-qualification milestone spans phases 1–7.

The 2,000-character goal limit and the `"skeleton_ready"` status are the initial defaults. Phase one introduced independent state collections; phase two replaces their temporary data formats with the domain models described below.

Research, qualification, search, model calls, memory, database storage, email writing, reviews, approvals, and Gmail integration remain in their later phases.

LangGraph, Redis, Celery, queues, vector databases, model routing, generic `BaseAgent` abstractions, and autonomous loops remain deferred.

## Phase Two: Give workflow results a consistent format

**Status: implemented and verified.**

Each future workflow component needs a clear format for its results so the next component can use them reliably. Phase two adds five records:

| Record | Purpose |
|---|---|
| `Prospect` | Store researched company details, useful signals, potential decision-makers, and source references |
| `Qualification` | Keep a prospect's score, qualification decision, and reasons |
| `OutreachStrategy` | Describe the outreach angle and proposed next action |
| `EmailDraft` | Hold the email subject and body for a prospect |
| `ReviewResult` | Record the reviewer's decision, score, and issues |

The state now holds these records instead of loose dictionaries. It also includes `qualification_results` so scores and explanations remain available alongside the selected prospects. Strategies, drafts, and reviews remain organized by prospect ID.

Unknown website, industry, and decision-maker details can stay empty as `null`. Required text must contain more than whitespace, and unexpected fields are rejected. Each record gets its own result lists. Qualification scores must be whole numbers from 0–100, and decisions must be booleans. Review scores must be finite numbers; the architecture has not specified their scale. Email body formatting is preserved.

### Phase-two completion checks

- [x] All five records contain the fields specified in the architecture.
- [x] State collections use the new record types and independent defaults.
- [x] Qualification results are retained separately from qualified prospects.
- [x] Tests reject missing required fields, invalid text, invalid decisions, and invalid scores.
- [x] Populated records and state can be converted to JSON and restored without losing information.
- [x] API responses and documentation use the structured records, including `qualification_results`.
- [x] The full suite passes: 119 tests, without external API calls.

The next phase is **phase three: a shared, mockable interface for structured model calls**. The application continues returning `"skeleton_ready"` with empty result collections until the research and qualification workflow is implemented.
