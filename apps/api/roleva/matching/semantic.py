"""Tier three: semantic matching for wordings the taxonomy does not know.

The lexicon handles named tools well and phrasing badly. A posting asking for
"experience presenting technical work to non-technical audiences" will never
appear in an alias table, but a resume bullet reading "presented quarterly
findings to the merchandising team" plainly satisfies it.

Embeddings close that gap. Requirements and resume bullets go into **one**
batched call — embedding each string separately would exhaust a per-minute
quota on its own — and the results are compared by cosine similarity.

The output is a band rather than a verdict:

    >= 0.82   accept
    0.62-0.82 ambiguous, worth a model call
    <  0.62   reject

Only the middle band costs anything further. Everything outside it is settled
here, for the price of a single request.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from roleva.llm.client import LlmClient
from roleva.models.common import Provenance, Span
from roleva.models.evidence import Evidence
from roleva.models.job import Requirement
from roleva.models.resume import SkillOrigin

#: At or above this, two texts mean the same thing.
SEMANTIC_ACCEPT = 0.82

#: Below this, they do not. Between the two is genuinely uncertain.
SEMANTIC_REJECT = 0.62


@dataclass
class EmbeddingCache:
    """Vectors keyed by a hash of their text.

    Requirements repeat heavily across analyses — thousands of postings ask for
    "strong communication skills" — so caching turns a popular requirement into
    a free lookup. Keyed by content hash rather than the text itself so the
    cache never holds resume content in a readable form.
    """

    vectors: dict[str, list[float]] = field(default_factory=dict)
    hits: int = 0
    misses: int = 0

    @staticmethod
    def key(text: str) -> str:
        return hashlib.sha256(text.strip().lower().encode("utf-8")).hexdigest()[:32]

    def get(self, text: str) -> list[float] | None:
        found = self.vectors.get(self.key(text))
        if found is None:
            self.misses += 1
        else:
            self.hits += 1
        return found

    def put(self, text: str, vector: list[float]) -> None:
        self.vectors[self.key(text)] = vector

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0


@dataclass(frozen=True)
class Candidate:
    """A piece of resume content a requirement might be satisfied by."""

    text: str
    origin: SkillOrigin
    span: Span


@dataclass(frozen=True)
class SemanticResult:
    requirement_id: str
    candidate: Candidate | None
    similarity: float

    @property
    def accepted(self) -> bool:
        return self.similarity >= SEMANTIC_ACCEPT

    @property
    def ambiguous(self) -> bool:
        return SEMANTIC_REJECT <= self.similarity < SEMANTIC_ACCEPT

    @property
    def rejected(self) -> bool:
        return self.similarity < SEMANTIC_REJECT


def cosine(left: list[float], right: list[float]) -> float:
    """Cosine similarity, clamped to [0, 1].

    Negative similarity means the texts point in opposite directions, which for
    this purpose is simply "unrelated" — there is no such thing as less than no
    match.
    """
    if not left or not right or len(left) != len(right):
        return 0.0

    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = sum(a * a for a in left) ** 0.5
    right_norm = sum(b * b for b in right) ** 0.5

    if left_norm == 0 or right_norm == 0:
        return 0.0

    return float(max(0.0, min(1.0, dot / (left_norm * right_norm))))


async def embed_texts(
    client: LlmClient,
    texts: list[str],
    *,
    cache: EmbeddingCache,
    analysis_budget: object = None,
) -> dict[str, list[float]]:
    """Embed many texts in one request, using the cache where possible.

    Returns a mapping from text to vector. Anything already cached costs
    nothing; the remainder go in a single batched call, and no call is made at
    all when the cache covers everything.
    """
    unique = list(dict.fromkeys(text.strip() for text in texts if text.strip()))
    if not unique:
        return {}

    result: dict[str, list[float]] = {}
    missing: list[str] = []

    for text in unique:
        cached = cache.get(text)
        if cached is None:
            missing.append(text)
        else:
            result[text] = cached

    if missing:
        vectors = await client.embed(
            missing,
            analysis_budget=analysis_budget,  # type: ignore[arg-type]
            label="embed",
        )
        for text, vector in zip(missing, vectors, strict=False):
            cache.put(text, vector)
            result[text] = vector

    return result


async def resolve_semantically(
    *,
    client: LlmClient,
    requirements: list[Requirement],
    candidates: list[Candidate],
    cache: EmbeddingCache,
    analysis_budget: object = None,
) -> list[SemanticResult]:
    """Score each unsettled requirement against the resume's own content.

    Every requirement and every candidate is embedded in one call, then each
    requirement takes its best-matching candidate. Comparison is against actual
    resume bullets rather than a skill list, so the candidate's origin still
    determines how much the evidence is worth.
    """
    if not requirements or not candidates:
        return [SemanticResult(r.id, None, 0.0) for r in requirements]

    requirement_texts = [r.text for r in requirements]
    candidate_texts = [c.text for c in candidates]

    vectors = await embed_texts(
        client,
        requirement_texts + candidate_texts,
        cache=cache,
        analysis_budget=analysis_budget,
    )

    results: list[SemanticResult] = []
    for requirement in requirements:
        requirement_vector = vectors.get(requirement.text.strip())
        if requirement_vector is None:
            results.append(SemanticResult(requirement.id, None, 0.0))
            continue

        best: tuple[Candidate, float] | None = None
        for candidate in candidates:
            candidate_vector = vectors.get(candidate.text.strip())
            if candidate_vector is None:
                continue
            score = cosine(requirement_vector, candidate_vector)
            if best is None or score > best[1]:
                best = (candidate, score)

        if best is None:
            results.append(SemanticResult(requirement.id, None, 0.0))
        else:
            results.append(SemanticResult(requirement.id, best[0], round(best[1], 4)))

    return results


def to_evidence(result: SemanticResult) -> Evidence | None:
    """Turn an accepted semantic result into evidence.

    The similarity is recorded so the UI can show *how* confident the match was
    — a 0.95 and a 0.83 are both accepted, and a user deserves to know which
    one they have.
    """
    if result.candidate is None or not result.accepted:
        return None

    return Evidence(
        span=result.candidate.span,
        origin=result.candidate.origin,
        provenance=Provenance.SEMANTIC,
        similarity=result.similarity,
        note="matched by meaning rather than wording",
    )
