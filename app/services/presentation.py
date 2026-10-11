"""Plain-language Telegram summaries; detailed diagnostics stay in the dashboard."""


def source_summary(reference, label):
    """Keep useful web links and page numbers without displaying private IDs."""
    if reference.startswith(('https://', 'http://')):
        return f'{label} — {reference}'
    page = reference.partition('#page=')[2]
    if page.isdigit() and not label.endswith(f'page {page}'):
        return f'{label}, page {page}'
    return label


def draft_button(request):
    return 'Create draft' if request.draft_mode == 'direct' and len(request.recipients) == 1 else 'Create drafts'


def proposal_summary(request, limit):
    """Explain what the owner is confirming, without exposing configuration."""
    if request.draft_mode == 'direct':
        addresses = ', '.join(recipient.email for recipient in request.recipients.values())
        text = f"I'll prepare {'an email' if len(request.recipients) == 1 else 'emails'} to {addresses}.\n\n{request.goal}"
    else:
        text = f"I'll research suitable contacts and prepare up to {limit} email drafts.\n\n{request.goal}"
    destination = 'save them in Gmail for you to review and send yourself' if request.gmail_action == 'draft' else 'keep them here for your review'
    return text + f'\n\nTap {draft_button(request)} and I’ll {destination}.'


def run_summary(state):
    """Return a useful outcome, including a bounded preview of saved drafts."""
    saved = [identifier for identifier, outcome in state.outcomes.items() if outcome.status == 'drafted']
    if saved:
        text = 'Your draft is ready in Gmail.' if len(saved) == 1 else f'Your {len(saved)} drafts are ready in Gmail.'
        for identifier in saved:
            draft = state.drafts[identifier]
            preview = draft.body[:1200]
            if len(draft.body) > 1200:
                preview += '\n[Preview shortened; the full email is in Gmail.]'
            text += f'\n\nTo: {state.recipients[identifier].email}\nSubject: {draft.subject}\n\n{preview}'
        if len(saved) < len(state.qualified_prospects):
            text += '\n\nSome drafts could not be saved. You can check the details in the dashboard.'
        return text + '\n\nReview and edit them in Gmail → Drafts, then click Send yourself.\nhttps://mail.google.com/mail/#drafts'
    if state.current_step == 'awaiting_recipients':
        return 'I found contacts to write to. I need you to choose their email addresses before I can prepare the drafts.'
    if state.current_step == 'awaiting_approval':
        return 'Your drafts are ready for you to review. You can edit them or choose which ones to keep.'
    if state.current_step == 'no_matches':
        return "I couldn't find suitable contacts from the information available. Share a website, contact, or a little more detail and I can try again."
    if state.current_step == 'stopped':
        return "I've stopped and saved your progress. Say continue when you're ready."
    if state.current_step == 'cancelled':
        return 'Your request has been cancelled.'
    if any(outcome.status == 'uncertain' for outcome in state.outcomes.values()):
        return "Gmail didn't confirm whether the draft was saved. Please check Gmail Drafts before trying again."
    if any('opted out' in outcome.reason for outcome in state.outcomes.values()):
        return "I didn't create a draft because this contact has asked not to receive email."
    if state.failures:
        return "I couldn't finish preparing these emails. Please check the connection and review details in the dashboard before trying again."
    if any(outcome.status == 'manual_review' for outcome in state.outcomes.values()):
        return 'The email needs another review before it can be saved in Gmail. You can inspect the draft in the dashboard.'
    if any(outcome.status in {'blocked', 'failed'} for outcome in state.outcomes.values()):
        return "I couldn't save these drafts because a contact check needs attention. The dashboard has the details."
    if state.drafts:
        return 'Your drafts are saved in the dashboard for you to review.'
    return "I couldn't prepare a draft from that request. Tell me who it's for and what you'd like it to say."
