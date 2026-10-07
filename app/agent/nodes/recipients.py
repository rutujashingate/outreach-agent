"""Resolve publicly sourced addresses before memory lookup and contact rules."""
from langgraph.types import interrupt
from app.domain.workflow import Recipient, Outcome


async def prepare_recipients(state, runtime):
    if not state.discover_emails:
        return {}
    recipients, candidates, pending = dict(state.recipients), {}, []
    for prospect in state.qualified_prospects:
        if prospect.id in recipients: continue
        matches = {}
        for page in state.pages:
            if page.error or page.url not in prospect.sources: continue
            names = [prospect.company_name, prospect.decision_maker_name]
            if not any(name and name.casefold() in page.text.casefold() for name in names): continue
            for email, quote in page.emails.items():
                try: matches[email] = Recipient(email=email, source=page.url, evidence_quote=quote[:2000])
                except ValueError: continue
        candidates[prospect.id] = list(matches.values())
        if len(matches) == 1: recipients[prospect.id] = next(iter(matches.values()))
        else: pending.append(prospect.id)
    return {'recipients': recipients, 'recipient_candidates': candidates, 'recipient_requests': pending,
            'current_step': 'awaiting_recipients' if pending else 'qualified'}


def validate_selections(state, selections):
    if set(selections) != set(state.recipient_requests):
        raise ValueError('Select an address or skip each pending prospect.')
    for item in selections.values():
        if item is not None: Recipient.model_validate(item)


async def choose_recipients(state, runtime):
    submitted = interrupt({'kind': 'recipients', 'run_id': state.run_id, 'prospect_ids': state.recipient_requests})
    selections = submitted.get('recipients', {})
    validate_selections(state, selections)
    recipients, outcomes = dict(state.recipients), dict(state.outcomes)
    for prospect_id, value in selections.items():
        if value is None:
            outcomes[prospect_id] = Outcome(prospect_id=prospect_id, status='blocked',
                reason='Owner skipped recipient selection.', source=f'run:{state.run_id}:recipients')
        else:
            selected = Recipient.model_validate(value)
            known = next((r for r in state.recipient_candidates.get(prospect_id, []) if r.email.casefold() == selected.email.casefold()), None)
            recipients[prospect_id] = known or Recipient(email=selected.email, source='Explicitly supplied by the owner')
    return {'recipients': recipients, 'outcomes': outcomes, 'recipient_requests': [], 'current_step': 'qualified'}
