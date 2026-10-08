"""Connect optional search and the existing researcher to the full graph."""

from langgraph.runtime import Runtime

from app.agent.components.researcher import Researcher
from app.domain.workflow import WorkflowState
from app.agent.context import WorkflowContext


async def discovery_node(state: WorkflowState, runtime: Runtime[WorkflowContext]) -> dict:
    context = runtime.context
    from app.connectors.browser.managed import ManagedBrowser
    browser = ManagedBrowser(context.browser, context.repository, state.run_id, context.limits) if state.use_browser and context.browser else None
    researcher = Researcher(client=context.client, search_tool=context.search if state.use_search else None,
                            browser_tool=browser, seed_urls=state.seed_urls, max_pages=context.limits.max_browser_pages)
    from app.agent.nodes.documents import bounded_evidence, evidence_records
    records = [item for item in evidence_records(state.documents) if item['purpose'] == 'research']
    # Allocate a fair text share to each cited page so one long upload does not
    # hide all later sources. Never truncate serialized JSON midway through it.
    notes = state.research_material
    notices = list(state.document_warnings)
    if records:
        # Reserve at least half of the input for files, and leave room for
        # public browser evidence gathered by the researcher afterwards.
        shortened_notes = notes[:40000]
        material, clipped = bounded_evidence(records, 79999 - len(shortened_notes))
        if clipped or len(shortened_notes) < len(notes):
            notices.append('Research used shortened notes/file excerpts to fit the evidence limit. Full file text is available for inspection.')
        notes = shortened_notes + '\n' + material
    prospects = await researcher.research(goal=state.goal, research_material=notes,
                                          structured_goal=state.structured_goal)
    recipients = dict(state.recipients)
    for prospect in prospects:
        # An exact organization-name mapping is an explicit user choice too.
        if prospect.id not in recipients and prospect.company_name in recipients:
            recipients[prospect.id] = recipients[prospect.company_name]
    return {"prospects": prospects[:context.limits.max_discovered], "recipients": recipients,
            "search_results": researcher.search_results, "pages": researcher.pages, "research_material": researcher.evidence_material,
            "current_step": "research_complete", "document_warnings": notices}
