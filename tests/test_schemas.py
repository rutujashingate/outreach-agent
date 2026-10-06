"""Check that request and result records accept valid data and reject mistakes."""

import pytest
from pydantic import ValidationError

from app.models.schemas import (
    EmailDraft,
    OutreachRequest,
    OutreachStrategy,
    Prospect,
    Qualification,
    ReviewResult,
)


# parametrize runs the same test for each example. ids names those cases in
# test output, making a failure easier to identify.
@pytest.mark.parametrize(
    ("goal", "expected"),
    [
        ("Find AI startups", "Find AI startups"),
        (" \tFind  AI startups\n ", "Find  AI startups"),
        ("x", "x"),
        ("x" * 2000, "x" * 2000),
        ("  " + "x" * 2000 + "\n ", "x" * 2000),
    ],
    ids=["plain", "trim-preserve-wording", "minimum", "maximum", "trim-maximum"],
)
def test_valid_goal(goal, expected):
    request = OutreachRequest(goal=goal)

    assert request.goal == expected


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"goal": None},
        {"goal": ""},
        {"goal": " \t\n "},
        {"goal": 42},
        {"goal": 3.14},
        {"goal": True},
        {"goal": ["Find startups"]},
        {"goal": {"text": "Find startups"}},
        {"goal": b"Find startups"},
        {"goal": "x" * 2001},
        {"goal": "Find startups", "unexpected": "value"},
    ],
    ids=[
        "missing", "null", "empty", "whitespace", "integer", "float",
        "boolean", "list", "object", "bytes", "too-long", "extra-field",
    ],
)
def test_invalid_goal_or_request(payload):
    # This test succeeds when Pydantic raises the expected validation error.
    with pytest.raises(ValidationError):
        OutreachRequest.model_validate(payload)


DOMAIN_MODELS = [Prospect, Qualification, OutreachStrategy, EmailDraft, ReviewResult]


@pytest.mark.parametrize("model", DOMAIN_MODELS)
def test_domain_models_round_trip_json(model, records):
    record = records[model]

    # Turn the record into JSON text, then reconstruct a record from that text.
    restored = model.model_validate_json(record.model_dump_json())

    assert restored == record
    assert restored.model_dump(mode="json") == record.model_dump(mode="json")


@pytest.mark.parametrize(
    ("model", "field"),
    [
        (Prospect, "id"),
        (Prospect, "company_name"),
        (Qualification, "prospect_id"),
        (Qualification, "score"),
        (Qualification, "qualified"),
        (OutreachStrategy, "prospect_id"),
        (OutreachStrategy, "trigger"),
        (OutreachStrategy, "pain_hypothesis"),
        (OutreachStrategy, "value_proposition"),
        (OutreachStrategy, "personalization_hook"),
        (OutreachStrategy, "call_to_action"),
        (EmailDraft, "prospect_id"),
        (EmailDraft, "subject"),
        (EmailDraft, "body"),
        (ReviewResult, "prospect_id"),
        (ReviewResult, "approved"),
        (ReviewResult, "score"),
    ],
)
def test_domain_models_require_core_fields(model, field, records):
    # model_dump turns a record into an ordinary Python dictionary. Removing
    # one field checks whether incomplete data is correctly rejected.
    payload = records[model].model_dump()
    del payload[field]

    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize("model", DOMAIN_MODELS)
def test_domain_models_reject_unknown_fields(model, records):
    payload = records[model].model_dump()
    payload["unexpected"] = "value"

    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_unknown_prospect_details_can_be_omitted():
    prospect = Prospect(id="p1", company_name="Example AI")

    assert prospect.website is None
    assert prospect.industry is None
    assert prospect.decision_maker_name is None
    assert prospect.decision_maker_role is None
    assert prospect.signals == []
    assert prospect.sources == []


@pytest.mark.parametrize(
    ("model", "field", "value"),
    [
        (Prospect, "id", ""),
        (Prospect, "company_name", " \n "),
        (Prospect, "website", " "),
        (Prospect, "signals", [42]),
        (Prospect, "sources", [" "]),
        (Qualification, "prospect_id", " "),
        (Qualification, "reasons", [None]),
        (OutreachStrategy, "trigger", ""),
        (OutreachStrategy, "call_to_action", " \t "),
        (EmailDraft, "subject", " "),
        (EmailDraft, "body", " \n\t "),
        (ReviewResult, "issues", [False]),
    ],
)
def test_domain_models_reject_blank_or_incorrect_text(model, field, value, records):
    payload = records[model].model_dump()
    payload[field] = value

    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize("score", [0, 70, 100])
def test_qualification_accepts_scores_in_range(score):
    # A score and the decision are separate inputs. A future qualifier will
    # decide qualified; the schema checks that both fields have valid types.
    result = Qualification(prospect_id="p1", score=score, qualified=False)

    assert result.score == score
    assert result.qualified is False


@pytest.mark.parametrize("score", [-1, 101, 69.5, 70.0, "70", True])
def test_qualification_rejects_invalid_scores(score):
    with pytest.raises(ValidationError):
        Qualification(prospect_id="p1", score=score, qualified=False)


@pytest.mark.parametrize(
    ("model", "field"),
    [(Qualification, "qualified"), (ReviewResult, "approved")],
)
@pytest.mark.parametrize("value", ["true", 1, 0, None])
def test_decisions_require_actual_booleans(model, field, value, records):
    payload = records[model].model_dump()
    payload[field] = value

    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize("score", [float("nan"), float("inf"), float("-inf"), "0.9"])
def test_review_requires_a_finite_numeric_score(score):
    # NaN and infinity are special numeric values unsuitable for these records.
    with pytest.raises(ValidationError):
        ReviewResult(prospect_id="p1", approved=False, score=score)


def test_review_does_not_impose_an_unspecified_score_scale():
    review = ReviewResult(prospect_id="p1", approved=True, score=90.0)

    assert review.score == 90.0


def test_email_body_formatting_is_preserved():
    body = "  Hi Example Contact,\n\nA short technical conversation?\n"

    draft = EmailDraft(prospect_id="p1", subject="Hello", body=body)

    assert draft.body == body


@pytest.mark.parametrize(
    ("model", "field"),
    [
        (Prospect, "signals"),
        (Prospect, "sources"),
        (Qualification, "reasons"),
        (ReviewResult, "issues"),
    ],
)
def test_domain_collection_defaults_are_independent(model, field, records):
    # Omit this list field so both records must create their own default list.
    payload = records[model].model_dump(exclude={field})
    first = model.model_validate(payload)
    second = model.model_validate(payload)

    # getattr reads the attribute whose name is stored in the field variable.
    getattr(first, field).append("First record only")

    assert getattr(second, field) == []
