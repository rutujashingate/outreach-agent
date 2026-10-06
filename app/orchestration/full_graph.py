"""The complete workflow, split into research and message-preparation graphs.

The original research-only graph is retained for existing callers. This graph
adds checkpointed runs, explicit routing, review limits, and human approval.
"""

import time

from langgraph.errors import GraphInterrupt
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from app.models.workflow import WorkflowState
from app.observability import trace
from app.orchestration.context import WorkflowContext
from app.orchestration.nodes.approval import human_approval, prepare_approval
from app.orchestration.nodes.contact import contact_node
from app.orchestration.nodes.discovery import discovery_node
from app.orchestration.nodes.external import external_node, finish_node
from app.orchestration.nodes.goal import goal_node
from app.orchestration.nodes.memory import memory_node
from app.orchestration.nodes.qualification import qualification_node
from app.orchestration.nodes.review import review_node
from app.orchestration.nodes.strategy import strategy_node
from app.orchestration.nodes.writing import writing_node
from app.orchestration.routing import (
    after_contact_policy, after_human_approval, after_prepare_approval, after_qualification, after_review,
)


def observed(name, function):
    """Record node timing and decisions while keeping business logic elsewhere."""
    async def node(state: WorkflowState, runtime: Runtime[WorkflowContext]) -> dict:
        context, started = runtime.context, time.monotonic()
        trace(context.repository, state.run_id, "node_start", node=name)
        try:
            result = await function(state, runtime)
        except GraphInterrupt:
            trace(context.repository, state.run_id, "interrupt", node=name)
            raise
        except Exception as error:
            trace(context.repository, state.run_id, "node_failure", node=name, error_type=type(error).__name__)
            raise
        trace(context.repository, state.run_id, "node_end", node=name,
              seconds=time.monotonic() - started, current_step=result.get("current_step"))
        if name in {"qualification", "contact_policy", "prepare_approval", "human_approval", "review"}:
            updated = state.model_copy(update=result)
            route = {"qualification": after_qualification, "contact_policy": after_contact_policy,
                     "prepare_approval": after_prepare_approval, "human_approval": after_human_approval,
                     "review": after_review}[name](updated)
            trace(context.repository, state.run_id, "route", node=name, destination=route,
                  revisions=updated.revision_counts)
        return result
    return node


def build_research_graph():
    builder = StateGraph(WorkflowState, context_schema=WorkflowContext)
    builder.add_node("interpret_goal", observed("interpret_goal", goal_node))
    builder.add_node("research", observed("research", discovery_node))
    builder.add_node("qualification", observed("qualification", qualification_node))
    builder.add_edge(START, "interpret_goal")
    builder.add_edge("interpret_goal", "research")
    builder.add_edge("research", "qualification")
    builder.add_edge("qualification", END)
    # Parent checkpointing is inherited; no separate relationship database is
    # substituted for LangGraph's execution checkpoints.
    return builder.compile()


def build_outreach_graph():
    builder = StateGraph(WorkflowState, context_schema=WorkflowContext)
    for name, function in (("strategy", strategy_node), ("writing", writing_node), ("review", review_node)):
        builder.add_node(name, observed(name, function))
    builder.add_edge(START, "strategy")
    builder.add_edge("strategy", "writing")
    builder.add_edge("writing", "review")
    builder.add_conditional_edges("review", after_review, {"writing": "writing", "end": END})
    return builder.compile()


def build_full_graph(checkpointer):
    builder = StateGraph(WorkflowState, context_schema=WorkflowContext)
    builder.add_node("research", build_research_graph())
    builder.add_node("outreach", build_outreach_graph())
    for name, function in (
        ("memory_check", memory_node), ("contact_policy", contact_node),
        ("prepare_approval", prepare_approval), ("human_approval", human_approval),
        ("external_actions", external_node), ("finish", finish_node),
    ):
        builder.add_node(name, observed(name, function))
    builder.add_edge(START, "research")
    builder.add_conditional_edges("research", after_qualification,
                                  {"memory_check": "memory_check", "finish": "finish"})
    builder.add_edge("memory_check", "contact_policy")
    builder.add_conditional_edges("contact_policy", after_contact_policy,
                                  {"outreach": "outreach", "finish": "finish"})
    builder.add_edge("outreach", "prepare_approval")
    builder.add_conditional_edges("prepare_approval", after_prepare_approval,
                                  {"human_approval": "human_approval", "external_actions": "external_actions"})
    builder.add_conditional_edges("human_approval", after_human_approval,
                                  {"outreach": "outreach", "external_actions": "external_actions"})
    builder.add_edge("external_actions", "finish")
    builder.add_edge("finish", END)
    return builder.compile(checkpointer=checkpointer)
