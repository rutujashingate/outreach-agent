"""Retrieve a small set of recent facts for the correct contact and goal."""

from datetime import timedelta
import re

from app.memory.repository import Repository
from app.models.workflow import MemoryFact, utc_now
from app.security.limits import Limits


def candidates(repository: Repository, email: str, limits: Limits) -> list[MemoryFact]:
    now = utc_now()
    return [fact for fact in repository.facts(email) if fact.kind == "opt_out" or (
        (fact.expires_at is None or fact.expires_at > now)
        and fact.recorded_at >= now - timedelta(days=limits.memory_max_age_days)
    )]


def retrieve(repository: Repository, email: str, goal: str, limits: Limits) -> list[MemoryFact]:
    words = set(re.findall(r"\w+", goal.casefold()))
    facts = candidates(repository, email, limits)
    # Relationship constraints are relevant even without a shared keyword.
    important = {"opt_out", "timing", "objection", "preference", "relationship"}
    facts = [fact for fact in facts if fact.kind in important or
             words.intersection(re.findall(r"\w+", fact.value.casefold()))]
    facts.sort(key=lambda fact: (
        fact.kind == "opt_out", len(words.intersection(re.findall(r"\w+", fact.value.casefold()))),
        fact.recorded_at,
    ), reverse=True)
    return facts[:limits.memory_limit]
