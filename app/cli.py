"""V1's terminal interface: enter goals and review saved work in plain language.

Run `python -m app.cli`, or try fictional data with `python -m app.cli --demo`.
The terminal calls the existing manager directly; an HTTP server is optional.
"""

import argparse
import asyncio
from contextlib import asynccontextmanager
import os

from langgraph.errors import GraphRecursionError
from pydantic import ValidationError

from app.models.client import ModelClientError
from app.models.groq_client import DEFAULT_GROQ_MODEL
from app.models.schemas import EmailDraft
from app.models.workflow import ApprovalDecision, ApprovalSubmission, RunResponse, WorkflowRequest
from app.orchestration.runs import ConfigurationError, RunConflict, RunManager, RunNotFound
from app.orchestration.runtime import open_runtime
from app.security.limits import LimitExceeded
from app.settings import Settings
from app.tools.search import ToolError


def read_text(prompt: str, *, default: str = "", read=input) -> str:
    """Collect several lines; a single dot ends input and preserves line breaks."""
    print(prompt)
    print('Finish with a line containing only ".".' + (' Use "." immediately to keep the current text.' if default else ''))
    lines = []
    while True:
        line = read('> ')
        if line == '.':
            value = '\n'.join(lines)
            return value if value.strip() else default
        lines.append(line)


def choose(prompt: str, choices: tuple[str, ...], *, default: str, read=input) -> str:
    """Keep asking until the user supplies an offered choice."""
    while True:
        answer = read(f'{prompt} ({" / ".join(choices)}) [{default}]: ').strip().casefold() or default
        if answer in choices:
            return answer
        print('Choose one of: ' + ', '.join(choices))


def collect_request(*, read=input) -> WorkflowRequest:
    """Turn ordinary questions into the same validated request used by the API."""
    goal = read('What is your outreach goal? ')
    sender = {
        'name': read('Your name [User]: ').strip() or 'User',
        'email': read('Your email (optional for review-only runs): ').strip() or None,
        'context': read_text('Your background or product details (optional):', read=read),
    }
    use_search = choose('Search the web? Requires a Brave key', ('yes', 'no'), default='no', read=read) == 'yes'
    material = read_text('Research notes and source URLs (optional alongside search):', read=read)
    print('Enter known recipients. Use the target name exactly as it appears in the evidence, or its prospect ID.')
    recipients = {}
    while True:
        target = read('Target name or ID (press Enter when finished): ').strip()
        if not target:
            break
        if target in recipients:
            print('This target is already entered. Use a different target or press Enter to finish.')
            continue
        recipients[target] = {'email': read('Recipient email: ').strip(), 'source': 'Entered by the user in the CLI'}
    action = choose('After approval, record the result or create a Gmail draft', ('none', 'draft'), default='none', read=read)
    return WorkflowRequest(goal=goal, sender=sender, research_material=material,
                           recipients=recipients, use_search=use_search, gmail_action=action)


def show_configuration(settings: Settings) -> bool:
    """Show which settings exist without exposing secrets or calling providers."""
    provider = settings.model_provider
    required_key = 'GROQ_API_KEY' if provider == 'groq' else 'OPENAI_API_KEY'
    model = (os.getenv('GROQ_MODEL') or DEFAULT_GROQ_MODEL) if provider == 'groq' else os.getenv('OPENAI_MODEL', '')
    ready = bool(os.getenv(required_key, '').strip() and model.strip())
    print(f'Model provider: {provider}; model: {model or "MISSING"}')
    for key in (required_key, 'BRAVE_SEARCH_API_KEY', 'GMAIL_ACCESS_TOKEN'):
        print(f'{key}: ' + ('configured' if os.getenv(key, '').strip() else 'MISSING'))
    print('Configuration presence checked only; keys have not been authenticated with their providers.')
    if settings.database_url:
        print('Relationship database: custom OUTREACH_DATABASE_URL (connection details hidden)')
    else:
        print(f'Relationship database: SQLite at {settings.data_dir / "relationships.sqlite3"}')
    if settings.checkpoint_backend == 'sqlite':
        print(f'Saved workflow progress: SQLite at {settings.data_dir / "checkpoints.sqlite3"}')
    else:
        print(f'Saved workflow progress backend: {settings.checkpoint_backend}')
    print(f'Gmail history reading: {"enabled" if settings.read_gmail else "disabled"}')
    print(f'Sending: {"enabled" if settings.sending_enabled else "disabled"}')
    print('The local CLI does not need OUTREACH_API_KEY; that setting protects the optional HTTP API.')
    return ready


def show_run(response: RunResponse) -> None:
    """Print results and failures, including the identifier needed after restart."""
    state = response.state
    print(f'\nRun: {state.run_id}\nGoal: {state.goal}\nProgress: {state.current_step}')
    print(f'Prospects found: {len(state.prospects)}; qualified: {len(state.qualified_prospects)}')
    scores = {item.prospect_id: item.score for item in state.qualification_results}
    for prospect in state.prospects:
        print(f'  {prospect.id}: {prospect.company_name}; score: {scores.get(prospect.id, "not assessed")}')
    for prospect_id, outcome in state.outcomes.items():
        print(f'  {prospect_id}: {outcome.status}' + (f' — {outcome.reason}' if outcome.reason else ''))
    for prospect_id, reason in state.failures.items():
        print(f'  {prospect_id}: {reason}')
    for prospect_id, draft in state.drafts.items():
        print(f'\nDraft for {prospect_id}\nSubject: {draft.subject}\n{draft.body}')
    if response.error:
        print(f'Execution error: {response.error}')
    if response.awaiting_approval:
        print('\nWaiting for your decision. Choose "Review a paused run" in the menu.')


async def review_run(manager: RunManager, run_id: str, *, read=input) -> RunResponse | None:
    """Collect a decision for every pending draft, binding it to current content."""
    response = manager.get(run_id)
    if not response.awaiting_approval:
        print('This run is not waiting for approval.')
        show_run(response)
        return response
    print('Decisions are submitted together. Choosing later leaves the entire run paused.')
    decisions = []
    state = response.state
    for request in state.approval_requests:
        print(f'\nTarget: {request.prospect.company_name} ({request.prospect.id})')
        print(f'From: {state.sender.name} <{state.sender.email or "not supplied"}>')
        print(f'To: {request.recipient.email}; requested Gmail action: {state.gmail_action}')
        qualification = next((item for item in state.qualification_results if item.prospect_id == request.prospect.id), None)
        if qualification:
            print(f'Qualification score: {qualification.score}; reasons: ' + '; '.join(qualification.reasons))
        print('Research and sources:')
        for item in request.research_summary:
            print('  ' + item)
        print('Relationship history:')
        for fact in request.memories:
            print(f'  {fact.value} (source: {fact.source})')
        if not request.memories:
            print('  No relevant saved facts.')
        print('Strategy:')
        for name, value in request.strategy.items():
            if name != 'prospect_id':
                print(f'  {name.replace("_", " ")}: {value}')
        print(f'Message version: {request.version}\nSubject: {request.draft.subject}\n{request.draft.body}')
        action = choose('Your decision', ('approve', 'reject', 'edit', 'later'), default='later', read=read)
        if action == 'later':
            print('No decisions submitted. The run remains paused.')
            return None
        edited = None
        if action == 'edit':
            subject = read(f'Subject [{request.draft.subject}]: ').strip() or request.draft.subject
            body = read_text('New message body:', default=request.draft.body, read=read)
            edited = EmailDraft(prospect_id=request.prospect.id, subject=subject, body=body)
        decisions.append(ApprovalDecision(prospect_id=request.prospect.id, version=request.version,
            fingerprint=request.fingerprint, action=action, edited_draft=edited))
    result = await manager.resume(run_id, ApprovalSubmission(decisions=decisions))
    show_run(result)
    return result


def show_error(error: Exception) -> None:
    """Explain expected failures without printing provider payloads or credentials."""
    if isinstance(error, ValidationError):
        for problem in error.errors(include_input=False, include_url=False):
            print('Invalid ' + '.'.join(map(str, problem['loc'])) + ': ' + problem['msg'])
    elif isinstance(error, (ConfigurationError, RunConflict, RunNotFound, LimitExceeded, ValueError)):
        print('Could not complete: ' + str(error))
    elif isinstance(error, GraphRecursionError):
        print('The workflow step limit was reached.')
    else:
        print('A model or external service could not complete the request. Check configuration and saved events.')
    if getattr(error, 'run_id', None):
        print(f'Saved run: {error.run_id}. Inspect it or retry after fixing the cause.')


MENU = '''
1. Start an outreach run
2. List saved runs
3. View a saved run
4. Review a paused run (approve / reject / edit)
5. Retry a failed run
6. View execution events
7. Check configuration
0. Exit'''


async def interact(manager: RunManager, *, demo: bool = False, read=input):
    """Keep the same services open while the user works through the menu."""
    print('Outreach Agent — V1 CLI')
    if demo:
        print('DEMO: fictional data and fake services. No real Gmail drafts or emails. Runs disappear on exit.')
    else:
        show_configuration(manager.settings)
    latest_run_id = ''
    while True:
        print(MENU)
        choice = read('Choose an option: ').strip()
        try:
            if choice == '0':
                print('Goodbye.')
                return
            if choice == '1':
                if demo:
                    from app.demo import demo_request
                    request = demo_request()
                    print('Using the fictional PhD outreach example.')
                else:
                    request = collect_request(read=read)
                print('Running the workflow...')
                response = await manager.start(request)
                latest_run_id = response.state.run_id
                show_run(response)
            elif choice == '2':
                runs = manager.repository.list_runs()
                if not runs:
                    print('No saved outreach runs.')
                for run in runs:
                    print(f'{run["run_id"]} | {run["status"]} | {run["current_step"]} | {run["goal"]}')
                if len(runs) == 100:
                    print('Showing up to 100 runs, sorted by identifier.')
            elif choice in ('3', '4', '5', '6'):
                run_id = read(f'Run ID{f" [latest: {latest_run_id}]" if latest_run_id else ""}: ').strip() or latest_run_id
                if not run_id:
                    print('Supply a run ID from the saved-run list.')
                    continue
                if choice == '3':
                    show_run(manager.get(run_id))
                elif choice == '4':
                    await review_run(manager, run_id, read=read)
                elif choice == '5':
                    print('Retrying from saved progress...')
                    show_run(await manager.retry(run_id))
                else:
                    for event in manager.execution_events(run_id):
                        details = {name: value for name, value in event.items() if name not in ('timestamp', 'event')}
                        print(f'{event["timestamp"]} | {event["event"]} | {details}')
                latest_run_id = run_id
            elif choice == '7':
                show_configuration(manager.settings)
            else:
                print('Choose a menu number from 0 to 7.')
        except (ConfigurationError, RunConflict, RunNotFound, LimitExceeded, ValidationError,
                ModelClientError, ToolError, GraphRecursionError, TimeoutError, ValueError) as error:
            show_error(error)
            latest_run_id = getattr(error, 'run_id', None) or latest_run_id


@asynccontextmanager
async def cli_manager(*, demo: bool):
    if demo:
        from app.demo import build_demo_manager
        manager = build_demo_manager()
        try:
            yield manager
        finally:
            manager.repository.engine.dispose()
    else:
        async with open_runtime() as manager:
            yield manager


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Enter outreach goals and review drafts in the terminal.')
    options = parser.add_mutually_exclusive_group()
    options.add_argument('--demo', action='store_true', help='Use fictional data and fake tools; no keys required.')
    options.add_argument('--check-config', action='store_true', help='Check setting presence without authenticating keys or calling providers.')
    args = parser.parse_args(argv)
    try:
        if args.check_config:
            return 0 if show_configuration(Settings.from_env()) else 1
        async def run():
            async with cli_manager(demo=args.demo) as manager:
                # Look up input here so scripts/tests can replace it, too.
                await interact(manager, demo=args.demo, read=input)
        asyncio.run(run())
        return 0
    except EOFError:
        print('\nInput closed. Exiting the CLI.')
        return 0
    except KeyboardInterrupt:
        print('\nStopped. Reopen the CLI to inspect saved runs.')
        return 130
    except Exception as error:
        show_error(error)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
