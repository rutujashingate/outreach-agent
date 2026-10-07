# Contributing to Outreach Agent

Contributions are welcome: clearer documentation, bug fixes, tests, evaluation cases, and improvements to the outreach workflow. Start with the [README](README.md) to run the fictional demo and the [file guide](FILE_GUIDE.md) to understand the code and phase history.

## Contribution licensing

This project's code and documentation are licensed under the [MIT License](LICENSE). By submitting a contribution for inclusion in this repository, you agree to license that contribution under the same MIT License. You retain copyright in your contribution.

Submit work you created or have permission to contribute under these terms. For material from another project, preserve its required copyright and license notices, identify its origin in your pull request, and make sure its terms permit inclusion here. Dependencies and external services keep their own licenses and terms.

## Report a problem or propose an improvement

Open an [issue](https://github.com/rutujashingate/outreach-agent/issues) with what you expected, what happened, steps to reproduce it, and your Python version. Use fictional goals and contacts in examples. For a larger feature, discuss how it fits the shared Telegram/dashboard service and existing workflow before implementing it.

Useful starting points include improving instructions, adding representative evaluation cases, testing provider failures, and strengthening recovery behavior. The README summarizes implemented features; the file guide records the detailed implementation and phase history.

## Set up your local copy

Fork the repository into your GitHub account. Replace `YOUR_GITHUB_USERNAME` in these commands with your username:

```bash
git clone https://github.com/YOUR_GITHUB_USERNAME/outreach-agent.git
cd outreach-agent
git switch -c improve-outreach
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m app.main --demo
```

Python 3.12 or newer is required. Open http://127.0.0.1:8000 and use the demo password shown in the README. The demo uses fictional records and fake services, so it requires no model, search, or Gmail credentials. Run commands from the project folder.

## Make and check your change

- Keep each change focused on one problem. Reuse the existing request records, model interface, runtime, and workflow rather than introducing a second application path.
- Keep routing, contact restrictions, limits, and approval checks in Python code. Model output should pass record validation before later steps use it.
- Keep comments understandable for someone learning the project.
- Update `FILE_GUIDE.md` in the same change. Explain each changed file's purpose, its main inputs and outputs, and what any new tests check. Add a follow-up entry to the phase history when appropriate.
- Update the README or integration guide when setup or user behavior changes.
- Add or adjust meaningful tests for changed behavior. Automated tests should run without credentials or external API calls.

Run the automated checks and inspect your changes:

```bash
python -m pytest -q
git diff --check
git diff
```

For browser-connector changes, install Chromium with `python -m playwright install chromium`, then run `RUN_BROWSER_TESTS=1 python -m pytest`. This includes a real-browser fixture without external network calls.

For evaluation changes, also run:

```bash
python -m evals.run --output .data/evaluations.json
```

That evaluation command uses preset responses. Live evaluation requires explicit configuration and consumes model credits; describe which kind you ran.

Keep credentials, real contact information, email threads, local databases, and generated reports out of commits, issues, and pull requests. `.gitignore` excludes `.env`, `.data/`, virtual environments, and build artifacts. Review the actual diff before committing.

## Submit a pull request

Commit each completed, checked logical change together with its documentation updates, then push your branch to your fork and open a pull request against this repository.

Explain the problem, what changed, and how you checked it. Include an example of the new behavior when helpful, and identify any live integration checks that are still needed. Link the related issue if one exists. Keep discussion respectful and help reviewers reproduce your result.
