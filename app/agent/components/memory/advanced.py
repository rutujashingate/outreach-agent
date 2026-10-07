"""Optional memory improvements, kept separate from the default simple lookup.

Embeddings are supplied by the caller only after retrieval measurements justify
them. No embedding request, vector database, or provider is enabled by default.
"""

from collections import defaultdict
from math import isfinite, sqrt
import re

from app.storage.repository import Repository
from app.agent.components.memory.retrieval import candidates
from app.domain.workflow import MemoryFact, Record
from app.services.limits import Limits


class MemoryGroup(Record):
    fact: MemoryFact
    sources: list[str]


def consolidate(facts: list[MemoryFact]) -> list[MemoryGroup]:
    """Merge identical facts for display while retaining every supporting source."""
    groups = defaultdict(list)
    for fact in facts:
        key = (fact.contact_email.casefold(), fact.kind, " ".join(fact.value.casefold().split()))
        groups[key].append(fact)
    return [MemoryGroup(fact=max(group, key=lambda item: (item.recorded_at, item.confidence)),
                        sources=sorted({item.source for item in group})) for group in groups.values()]


def possible_conflicts(facts: list[MemoryFact]) -> list[tuple[str, str]]:
    """Flag conflicting explicit preferences conservatively, without deleting either."""
    pairs = []
    for index, first in enumerate(facts):
        for second in facts[index + 1:]:
            if first.contact_email.casefold() != second.contact_email.casefold() or first.kind != second.kind:
                continue
            # A possible conflict needs the same wording except an explicit
            # negation. Different ordinary facts are not treated as contradictions.
            normalize = lambda text: re.sub(r"\b(do not|not|never|don't)\b", "", text.casefold()).split()
            if first.value != second.value and normalize(first.value) == normalize(second.value):
                pairs.append((first.id, second.id))
    return pairs


def cosine(first: list[float], second: list[float]) -> float:
    if not first or len(first) != len(second) or not all(isfinite(number) for number in first + second):
        raise ValueError("Embeddings need finite vectors with the same nonzero dimension.")
    denominator = sqrt(sum(number * number for number in first)) * sqrt(sum(number * number for number in second))
    return sum(a * b for a, b in zip(first, second)) / denominator if denominator else 0


async def semantic_retrieve(repository: Repository, email: str, goal: str, limits: Limits,
                            *, embed, measured_reason: str) -> list[MemoryFact]:
    if not measured_reason.strip():
        raise ValueError("Semantic retrieval requires a recorded reason based on retrieval measurements.")
    facts = [group.fact for group in consolidate(candidates(repository, email, limits))]
    if not facts:
        return []
    vectors = await embed([goal] + [fact.value for fact in facts])
    if len(vectors) != len(facts) + 1:
        raise ValueError("Embedding response did not match the input count.")
    scored = [(fact, cosine(vectors[0], vector)) for fact, vector in zip(facts, vectors[1:])]
    scored.sort(key=lambda item: (item[0].kind == "opt_out", item[1], item[0].confidence, item[0].recorded_at), reverse=True)
    return [fact for fact, score in scored[:limits.memory_limit]]
