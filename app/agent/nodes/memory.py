"""Load relevant relationship context before contact rules and writing."""

import asyncio
from datetime import datetime, timedelta

from langgraph.runtime import Runtime

from app.agent.components.memory.extraction import extract_memories, record_explicit_opt_out
from app.agent.components.memory.retrieval import retrieve
from app.domain.workflow import WorkflowState, utc_now
from app.storage.events import trace
from app.agent.context import WorkflowContext
from app.connectors.gmail.client import contact_messages


async def memory_node(state: WorkflowState, runtime: Runtime[WorkflowContext]) -> dict:
    context, memories = runtime.context, {}
    for prospect in state.qualified_prospects:
        recipient = state.recipients.get(prospect.id)
        if recipient is None:
            memories[prospect.id] = []
            continue
        if context.read_gmail and context.gmail is not None:
            known_sources = {item["source"] for item in context.repository.history(recipient.email)}
            async with asyncio.timeout(context.limits.tool_timeout):
                trace(context.repository, state.run_id, "gmail_read_start", operation="search_threads", prospect_id=prospect.id)
                thread_ids = await context.gmail.search_threads(recipient.email, limit=3)
                trace(context.repository, state.run_id, "gmail_read_end", operation="search_threads", count=len(thread_ids))
            for thread_id in thread_ids[:3]:
                async with asyncio.timeout(context.limits.tool_timeout):
                    trace(context.repository, state.run_id, "gmail_read_start", operation="read_thread", thread_id=thread_id)
                    thread = await context.gmail.read_thread(thread_id)
                    trace(context.repository, state.run_id, "gmail_read_end", operation="read_thread", thread_id=thread_id)
                for message in contact_messages(thread, recipient.email)[:10]:
                    if message["source"] in known_sources:
                        continue
                    # Enforce explicit opt-outs before any optional model call.
                    opted_out = message["inbound"] and record_explicit_opt_out(
                        context.repository, recipient.email, message["source"], message["body"],
                    )
                    if not opted_out:
                        await extract_memories(context.repository, recipient.email, message["source"],
                                               message["body"], context.client)
                    if message["inbound"] and message.get("sent_at") is not None and not opted_out:
                        if message["sent_at"] > utc_now() - timedelta(days=context.limits.recent_contact_days):
                            context.repository.update_contact(recipient.email, active_conversation=True)
                    if state.sender.email and state.sender.email.casefold() in message["from_addresses"] and message["sent_at"]:
                        previous = context.repository.contact(recipient.email)["last_contact_at"]
                        if previous is None or message["sent_at"] > datetime.fromisoformat(previous):
                            context.repository.update_contact(recipient.email, last_contact_at=message["sent_at"].isoformat())
                    context.repository.record_event(recipient.email, message["source"], {
                        "kind": "gmail_message", "inbound": message["inbound"],
                    })
                    known_sources.add(message["source"])
        if context.memory_retriever is not None:
            async with asyncio.timeout(context.limits.model_timeout):
                memories[prospect.id] = await context.memory_retriever(
                    context.repository, recipient.email, state.goal, context.limits)
        else:
            memories[prospect.id] = retrieve(context.repository, recipient.email, state.goal, context.limits)
        if any(fact.contact_email.casefold() != recipient.email.casefold() for fact in memories[prospect.id]):
            raise ValueError("Memory retrieval returned another contact's information.")
    return {"memories": memories}
