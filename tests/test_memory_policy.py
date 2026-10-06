"""Check durable facts, policy decisions, timing, and reply-driven opt-outs."""

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import create_mock_engine

from app.db.database import create_database
from app.db.models import Base
from app.memory.advanced import consolidate, possible_conflicts, semantic_retrieve
from app.memory.extraction import extract_memories
from app.memory.repository import Repository
from app.memory.retrieval import retrieve
from app.models.client import FakeModelClient, ModelResponseError
from app.models.workflow import MemoryFact, Recipient, ReplyRequest, utc_now
from app.orchestration.replies import process_reply
from app.orchestration.runs import RunConflict
from app.security.contact_policy import check_contact
from app.security.limits import Limits


def fact(identifier="f1", **changes):
    return MemoryFact.model_validate({"id": identifier, "contact_email": "contact@example.com", "kind": "fact",
        "value": "Building Python APIs", "source": f"message:{identifier}", "evidence_quote": "Building Python APIs", **changes})


def test_memory_survives_new_repository_instance(tmp_path):
    url = f"sqlite:///{tmp_path / 'relationships.sqlite3'}"
    first = Repository(create_database(url))
    original = fact()
    first.store_fact(original)
    first.engine.dispose()
    second = Repository(create_database(url))
    try:
        assert second.facts("CONTACT@example.com") == [original]
        assert second.facts("other@example.com") == []
    finally:
        second.engine.dispose()


def test_tables_compile_for_postgresql_without_a_server():
    statements = []
    engine = create_mock_engine("postgresql+psycopg://", lambda sql, *args, **kwargs: statements.append(str(sql.compile(dialect=engine.dialect))))
    Base.metadata.create_all(engine)
    assert any("relationship_memory" in statement for statement in statements)
    assert any("external_actions" in statement for statement in statements)


def test_retrieval_excludes_other_contacts_old_and_unrelated_facts(make_run_manager):
    setup = make_run_manager()
    setup.repository.store_fact(fact())
    setup.repository.store_fact(fact("old", recorded_at=utc_now() - timedelta(days=500)))
    setup.repository.store_fact(fact("other", contact_email="other@example.com"))
    setup.repository.store_fact(fact("unrelated", value="Likes painting", evidence_quote="Likes painting"))
    setup.repository.store_fact(fact("expired", expires_at=utc_now() - timedelta(days=1)))
    results = retrieve(setup.repository, "contact@example.com", "Python API collaboration", Limits())
    assert [item.id for item in results] == ["f1"]


def test_old_opt_out_does_not_expire_and_cannot_be_silently_cleared(make_run_manager):
    setup = make_run_manager()
    setup.repository.store_fact(fact("stop", kind="opt_out", value="Do not contact",
        evidence_quote="Do not contact", recorded_at=utc_now() - timedelta(days=1000), expires_at=utc_now() - timedelta(days=1)))
    assert retrieve(setup.repository, "contact@example.com", "Python", Limits())[0].kind == "opt_out"
    assert not check_contact(setup.repository, Recipient(email="contact@example.com"), Limits()).allowed
    with pytest.raises(ValueError, match="consent"):
        setup.repository.update_contact("contact@example.com", opted_out=False)


@pytest.mark.parametrize("changes", [
    {"opted_out": True}, {"active_conversation": True},
    {"last_contact_at": utc_now().isoformat()}, {"reconnect_at": (utc_now() + timedelta(days=30)).isoformat()},
])
def test_each_contact_rule_blocks(make_run_manager, changes):
    setup = make_run_manager()
    setup.repository.update_contact("contact@example.com", **changes)
    result = check_contact(setup.repository, Recipient(email="contact@example.com"), Limits())
    assert result.allowed is False
    assert result.reasons


def test_contact_becomes_eligible_after_cooldown(make_run_manager):
    setup = make_run_manager()
    setup.repository.update_contact("contact@example.com", last_contact_at=(utc_now() - timedelta(days=15)).isoformat())
    assert check_contact(setup.repository, Recipient(email="contact@example.com"), Limits()).allowed
    assert not check_contact(setup.repository, None, Limits()).allowed


def test_memory_extraction_stores_exact_quote_instead_of_model_assumption(make_run_manager):
    setup = make_run_manager()
    client = FakeModelClient([{"facts": [{"kind": "preference", "value": "They must need our paid product", "evidence_quote": "I prefer short emails"}]}])
    facts = asyncio.run(extract_memories(setup.repository, "contact@example.com", "m1", "I prefer short emails", client))
    assert facts[0].value == "I prefer short emails"
    assert facts[0].source == "m1"


def test_unsupported_quote_does_not_store_any_partial_memory(make_run_manager):
    setup = make_run_manager()
    client = FakeModelClient([{"facts": [
        {"kind": "fact", "value": "Python", "evidence_quote": "Python"},
        {"kind": "fact", "value": "Invented", "evidence_quote": "Invented"},
    ]}])
    with pytest.raises(ModelResponseError):
        asyncio.run(extract_memories(setup.repository, "contact@example.com", "m1", "Python", client))
    assert setup.repository.facts("contact@example.com") == []


def test_explicit_unsubscribe_needs_no_model_and_blocks_future_outreach(make_run_manager):
    setup = make_run_manager(responses=[])
    request = ReplyRequest(contact_email="contact@example.com", source="gmail:reply-1", body="Please unsubscribe me.")
    first = asyncio.run(process_reply(setup.manager, request))
    second = asyncio.run(process_reply(setup.manager, request))
    assert first == second
    assert first.classification.category == "opt_out"
    assert setup.client.calls == []
    assert setup.repository.contact("contact@example.com")["opted_out"]
    assert len(setup.repository.history("contact@example.com")) == 1


@pytest.mark.parametrize("category", ["positive", "negative", "referral", "question", "later"])
def test_reply_categories_update_sourced_memory_without_followups(make_run_manager, category):
    body = "Can we reconnect on 2027-02-01?"
    setup = make_run_manager(responses=[{"category": category, "evidence_quote": body},
        {"facts": [{"kind": "timing", "value": body, "evidence_quote": body}]}])
    result = asyncio.run(process_reply(setup.manager, ReplyRequest(contact_email="contact@example.com", source="m1", body=body)))
    assert result.classification.category == category
    assert result.facts[0].source == "m1"
    assert setup.repository.contact("contact@example.com")["active_conversation"]
    assert setup.gmail.calls == []
    if category == "later":
        assert setup.repository.contact("contact@example.com")["reconnect_at"].startswith("2027-02-01")


def test_advanced_memory_merges_duplicates_without_losing_sources():
    groups = consolidate([fact("f1"), fact("f2")])
    assert len(groups) == 1
    assert groups[0].sources == ["message:f1", "message:f2"]
    conflicts = possible_conflicts([fact("yes", kind="preference", value="I prefer calls"),
                                   fact("no", kind="preference", value="I do not prefer calls")])
    assert conflicts == [("yes", "no")]


def test_optional_semantic_retrieval_uses_measured_reason_and_fake_vectors(make_run_manager):
    setup = make_run_manager()
    setup.repository.store_fact(fact("f1", value="Building web services", evidence_quote="Building web services"))
    setup.repository.store_fact(fact("f2", value="Painting landscapes", evidence_quote="Painting landscapes"))
    async def embed(texts):
        return [[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]]
    async def run():
        with pytest.raises(ValueError, match="measured|measurements"):
            await semantic_retrieve(setup.repository, "contact@example.com", "Python APIs", Limits(), embed=embed, measured_reason="")
        return await semantic_retrieve(setup.repository, "contact@example.com", "Python APIs", Limits(memory_limit=1),
                                       embed=embed, measured_reason="Fixture demonstrates a vocabulary mismatch.")
    assert asyncio.run(run())[0].id == "f1"


def test_reused_reply_source_cannot_hide_a_new_explicit_opt_out(make_run_manager):
    setup = make_run_manager(responses=[{"category": "positive", "evidence_quote": "Thanks"}, {"facts": []}])
    original = ReplyRequest(contact_email="contact@example.com", source="m1", body="Thanks")
    asyncio.run(process_reply(setup.manager, original))
    with pytest.raises(RunConflict, match="different reply"):
        asyncio.run(process_reply(setup.manager, original.model_copy(update={"body": "Do not contact me."})))
    assert setup.repository.contact("contact@example.com")["opted_out"]
    assert len(setup.client.calls) == 2
