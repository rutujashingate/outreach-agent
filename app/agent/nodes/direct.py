"""Prepare owner-selected recipients without inventing research or fit scores."""
from app.agent.nodes.documents import prepare_documents, bounded_evidence, evidence_records
from app.domain.schemas import Prospect, OutreachStrategy
from app.domain.workflow import OutreachGoal


async def prepare_direct(state, runtime):
    """Reuse the writing/review/action path for a requested ordinary email."""
    context = runtime.context
    if not state.recipients:
        raise ValueError('A direct draft needs a recipient.')
    if len(state.recipients) > context.limits.max_qualified:
        raise ValueError('The requested draft batch exceeds the configured limit.')
    loaded = await prepare_documents(state, runtime)
    prospects, strategies = [], {}
    for identifier, recipient in state.recipients.items():
        # This is a contact supplied by the owner, not a researched company.
        # Keep its original key so recipient/version/action records stay linked.
        prospect = Prospect(id=identifier, company_name=recipient.email,
            entity_type='person', sources=[recipient.source])
        prospects.append(prospect)
        strategies[identifier] = OutreachStrategy(prospect_id=identifier,
            trigger='The owner requested this email.',
            pain_hypothesis='No problem or sales hypothesis was supplied. Do not invent one.',
            value_proposition=state.goal,
            personalization_hook='Use only the supplied request and known context.',
            call_to_action='Include a request only if the owner asked for one.')
    # The shared writing nodes use this existing list of selected contacts.
    # No qualification result or fabricated fit score is created for them.
    return {**loaded, 'prospects': prospects, 'qualified_prospects': prospects,
        'strategies': strategies,
        'structured_goal': OutreachGoal(raw_goal=state.goal, goal_type='direct_email',
            objective=state.goal, target_entity='person',
            target_description='Recipients explicitly selected by the owner',
            desired_outcome='Create email drafts for the owner to review and send manually.'),
        'current_step': 'qualified'}


def direct_brief(state):
    """Give the writer/reviewer the same bounded request and supplied evidence."""
    if state.draft_mode != 'direct':
        return None
    documents, shortened = bounded_evidence(evidence_records(state.documents), 8000)
    return {'goal': state.goal, 'supplied_evidence': state.research_material[:8000],
            'documents': documents, 'documents_shortened': shortened}
