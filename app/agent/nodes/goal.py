"""Connect goal interpretation to graph state."""

from langgraph.runtime import Runtime

from app.agent.components.goal_interpreter import interpret_goal
from app.domain.workflow import WorkflowState
from app.agent.context import WorkflowContext


async def goal_node(state: WorkflowState, runtime: Runtime[WorkflowContext]) -> dict:
    import json
    from app.agent.nodes.documents import bounded_evidence, evidence_records
    # Keep the interpretation prompt bounded. Full research evidence is fed to
    # discovery separately; background documents describe the sender only.
    material, clipped = bounded_evidence(evidence_records(state.documents), 40000, 20000)
    documents = json.loads(material)['uploaded_documents'] if material else []
    goal = await interpret_goal(state.goal, runtime.context.client, documents)
    notices = list(state.document_warnings)
    if clipped: notices.append('Goal interpretation used shortened file excerpts. Inspect the files to see all extracted text.')
    return {"structured_goal": goal, "current_step": "interpreted", "document_warnings": notices}
