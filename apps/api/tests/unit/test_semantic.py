"""Tests for the semantic tier, adjudication, and the full four-tier pipeline.

A fake provider stands in for the embedding and model calls, so these run
offline and spend no quota. The assertions that matter are about *how many
requests each tier costs* — that is the constraint the whole design is shaped
around.
"""

from __future__ import annotations

from typing import Any

import pytest

from roleva.config import Settings
from roleva.llm.budget import AnalysisBudget, DailyBudget, InMemoryUsageStore
from roleva.llm.client import LlmClient
from roleva.matching.adjudicator import (
    LlmAdjudication,
    LlmVerdict,
    build_prompt,
    to_adjudications,
)
from roleva.matching.cascade import build_index
from roleva.matching.pipeline import MatchStats, build_candidates, match
from roleva.matching.semantic import (
    SEMANTIC_ACCEPT,
    SEMANTIC_REJECT,
    Candidate,
    EmbeddingCache,
    SemanticResult,
    cosine,
    embed_texts,
    resolve_semantically,
    to_evidence,
)
from roleva.models.common import Provenance, SourceDoc, Span
from roleva.models.evidence import MatchStatus
from roleva.models.job import JobTarget, Priority, Requirement, RequirementCategory
from roleva.models.resume import (
    Bullet,
    ExperienceItem,
    ResumeDocument,
    SkillMention,
    SkillOrigin,
)

RESUME_TEXT = """Ananya Deshmukh

Experience
Software Engineering Intern
Presented quarterly findings to the merchandising team
Built a Django service in Python

Skills
Python, Docker
"""


def span_for(text: str) -> Span:
    start = RESUME_TEXT.index(text)
    return Span(doc=SourceDoc.RESUME, start=start, end=start + len(text), text=text)


def make_document() -> ResumeDocument:
    return ResumeDocument(
        experience=[
            ExperienceItem(
                title="Software Engineering Intern",
                bullets=[
                    Bullet(
                        text="Presented quarterly findings to the merchandising team",
                        span=span_for("Presented quarterly findings to the merchandising team"),
                    ),
                    Bullet(
                        text="Built a Django service in Python",
                        span=span_for("Built a Django service in Python"),
                    ),
                ],
            )
        ],
        skills=[
            SkillMention(raw="Docker", origin=SkillOrigin.SKILLS_LIST, span=span_for("Docker")),
        ],
    )


def requirement(text: str, **kwargs: Any) -> Requirement:
    return Requirement(
        text=text,
        category=kwargs.pop("category", RequirementCategory.SOFT_SKILL),
        priority=kwargs.pop("priority", Priority.MUST),
        **kwargs,
    )


class FakeProvider:
    """Records every call so the cost of each tier can be asserted."""

    def __init__(
        self,
        responses: list[str] | None = None,
        embedding: dict[str, list[float]] | None = None,
    ) -> None:
        self.responses = list(responses or [])
        self.embedding = embedding or {}
        self.prompts: list[str] = []
        self.embed_batches: list[list[str]] = []

    async def generate_json(self, *, prompt: str, model: str, **_: Any) -> str:
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("FakeProvider ran out of responses")
        return self.responses.pop(0)

    async def embed(self, *, texts: list[str], model: str) -> list[list[float]]:
        self.embed_batches.append(list(texts))
        # Unknown texts get an orthogonal vector, so they match nothing.
        return [self.embedding.get(text, [0.0, 0.0, 1.0]) for text in texts]


def make_client(
    responses: list[str] | None = None,
    embedding: dict[str, list[float]] | None = None,
) -> tuple[LlmClient, FakeProvider]:
    settings = Settings(llm_max_rpm=600, llm_max_rpd=1000, gemini_api_key="test")
    provider = FakeProvider(responses, embedding)
    client = LlmClient(
        provider,
        settings,
        DailyBudget(InMemoryUsageStore(), settings.llm_max_rpd),
        backoff_base_seconds=0.0,
    )
    return client, provider


class TestCosine:
    def test_identical_vectors_score_one(self) -> None:
        assert cosine([1.0, 0.0], [1.0, 0.0]) == 1.0

    def test_orthogonal_vectors_score_zero(self) -> None:
        assert cosine([1.0, 0.0], [0.0, 1.0]) == 0.0

    def test_magnitude_does_not_matter(self) -> None:
        assert cosine([1.0, 1.0], [5.0, 5.0]) == pytest.approx(1.0)

    def test_opposite_vectors_clamp_to_zero(self) -> None:
        """There is no such thing as less than no match."""
        assert cosine([1.0, 0.0], [-1.0, 0.0]) == 0.0

    def test_mismatched_lengths_are_handled(self) -> None:
        assert cosine([1.0, 0.0], [1.0]) == 0.0

    def test_empty_vectors_are_handled(self) -> None:
        assert cosine([], []) == 0.0


class TestEmbeddingCache:
    def test_a_stored_vector_is_returned(self) -> None:
        cache = EmbeddingCache()
        cache.put("Python", [1.0, 0.0])
        assert cache.get("Python") == [1.0, 0.0]

    def test_lookup_ignores_case_and_spacing(self) -> None:
        cache = EmbeddingCache()
        cache.put("Python", [1.0])
        assert cache.get("  python  ") == [1.0]

    def test_the_cache_key_is_a_hash_not_the_text(self) -> None:
        """Content hashing means the cache never holds resume text readably."""
        cache = EmbeddingCache()
        cache.put("secret bullet text", [1.0])
        assert "secret" not in "".join(cache.vectors)

    def test_hits_and_misses_are_counted(self) -> None:
        cache = EmbeddingCache()
        cache.put("a", [1.0])
        cache.get("a")
        cache.get("b")
        assert cache.hit_rate == 0.5

    async def test_a_full_cache_makes_no_request(self) -> None:
        """A popular requirement becomes a free lookup."""
        client, provider = make_client()
        cache = EmbeddingCache()
        cache.put("Python", [1.0, 0.0, 0.0])

        await embed_texts(client, ["Python"], cache=cache)
        assert provider.embed_batches == []

    async def test_only_uncached_texts_are_requested(self) -> None:
        client, provider = make_client()
        cache = EmbeddingCache()
        cache.put("Python", [1.0, 0.0, 0.0])

        await embed_texts(client, ["Python", "Docker"], cache=cache)
        assert provider.embed_batches == [["Docker"]]

    async def test_everything_goes_in_one_batch(self) -> None:
        """Embedding one string per call would exhaust a per-minute quota."""
        client, provider = make_client()
        await embed_texts(client, ["a", "b", "c", "d"], cache=EmbeddingCache())
        assert len(provider.embed_batches) == 1
        assert len(provider.embed_batches[0]) == 4

    async def test_duplicates_are_only_embedded_once(self) -> None:
        client, provider = make_client()
        await embed_texts(client, ["a", "a", "b"], cache=EmbeddingCache())
        assert provider.embed_batches[0] == ["a", "b"]


class TestSemanticBands:
    def _result(self, similarity: float) -> SemanticResult:
        return SemanticResult("r1", None, similarity)

    def test_high_similarity_is_accepted(self) -> None:
        assert self._result(0.9).accepted is True

    def test_low_similarity_is_rejected(self) -> None:
        assert self._result(0.3).rejected is True

    def test_the_middle_band_is_ambiguous(self) -> None:
        """The only band worth spending a model call on."""
        assert self._result(0.7).ambiguous is True

    def test_the_bands_do_not_overlap(self) -> None:
        for similarity in (0.0, 0.5, SEMANTIC_REJECT, 0.7, SEMANTIC_ACCEPT, 1.0):
            result = self._result(similarity)
            assert sum([result.accepted, result.ambiguous, result.rejected]) == 1


class TestSemanticResolution:
    async def test_a_paraphrased_requirement_matches_a_bullet(self) -> None:
        """The whole reason this tier exists: no alias table contains
        "presenting technical work to non-technical audiences"."""
        vector = [1.0, 0.0, 0.0]
        client, _ = make_client(
            embedding={
                "Comfortable presenting to non-technical audiences": vector,
                "Presented quarterly findings to the merchandising team": vector,
            }
        )
        results = await resolve_semantically(
            client=client,
            requirements=[requirement("Comfortable presenting to non-technical audiences")],
            candidates=build_candidates(make_document(), RESUME_TEXT),
            cache=EmbeddingCache(),
        )
        assert results[0].accepted is True

    async def test_an_unrelated_requirement_is_rejected(self) -> None:
        client, _ = make_client(embedding={"Kubernetes cluster administration": [0.0, 1.0, 0.0]})
        results = await resolve_semantically(
            client=client,
            requirements=[requirement("Kubernetes cluster administration")],
            candidates=build_candidates(make_document(), RESUME_TEXT),
            cache=EmbeddingCache(),
        )
        assert results[0].rejected is True

    async def test_nothing_to_match_against_costs_no_request(self) -> None:
        client, provider = make_client()
        results = await resolve_semantically(
            client=client,
            requirements=[requirement("anything")],
            candidates=[],
            cache=EmbeddingCache(),
        )
        assert provider.embed_batches == []
        assert results[0].similarity == 0.0

    def test_accepted_results_carry_their_similarity(self) -> None:
        """A 0.95 and a 0.83 are both accepted; the user deserves to know which."""
        candidate = Candidate(
            text="Presented quarterly findings to the merchandising team",
            origin=SkillOrigin.EXPERIENCE_BULLET,
            span=span_for("Presented quarterly findings to the merchandising team"),
        )
        evidence = to_evidence(SemanticResult("r1", candidate, 0.91))
        assert evidence is not None
        assert evidence.similarity == 0.91
        assert evidence.provenance is Provenance.SEMANTIC

    def test_a_rejected_result_yields_no_evidence(self) -> None:
        assert to_evidence(SemanticResult("r1", None, 0.2)) is None


class TestAdjudication:
    def test_the_pairs_are_delimited(self) -> None:
        prompt = build_prompt([(requirement("Python"), SemanticResult("r1", None, 0.7))])
        assert "<pairs>" in prompt and "</pairs>" in prompt

    def test_embedded_instructions_are_declared_to_be_data(self) -> None:
        prompt = build_prompt([(requirement("Python"), SemanticResult("r1", None, 0.7))])
        assert "not directions for you" in prompt

    def test_the_model_is_told_not_to_return_numbers(self) -> None:
        """Scores are computed in Python; the model only supplies verdicts."""
        prompt = build_prompt([(requirement("Python"), SemanticResult("r1", None, 0.7))])
        assert "Do not return scores or numbers" in prompt

    def test_verdicts_become_strengths(self) -> None:
        req = requirement("Python")
        pairs = [(req, SemanticResult(req.id, None, 0.7))]
        results = to_adjudications(
            LlmAdjudication(verdicts=[LlmVerdict(requirement="Python", verdict="yes")]),
            pairs,
        )
        assert results[0].strength == 1.0

    def test_a_partial_verdict_scores_half(self) -> None:
        req = requirement("Python")
        pairs = [(req, SemanticResult(req.id, None, 0.7))]
        results = to_adjudications(
            LlmAdjudication(verdicts=[LlmVerdict(requirement="Python", verdict="partial")]),
            pairs,
        )
        assert results[0].strength == 0.5

    def test_a_missing_verdict_is_treated_as_no(self) -> None:
        req = requirement("Python")
        results = to_adjudications(
            LlmAdjudication(verdicts=[]), [(req, SemanticResult(req.id, None, 0.7))]
        )
        assert results[0].strength == 0.0

    def test_verdicts_are_matched_by_text_not_position(self) -> None:
        """A model that reorders its output would otherwise shift every verdict
        onto the wrong requirement."""
        first, second = requirement("Python"), requirement("Docker")
        pairs = [
            (first, SemanticResult(first.id, None, 0.7)),
            (second, SemanticResult(second.id, None, 0.7)),
        ]
        results = to_adjudications(
            LlmAdjudication(
                verdicts=[
                    LlmVerdict(requirement="Docker", verdict="yes"),
                    LlmVerdict(requirement="Python", verdict="no"),
                ]
            ),
            pairs,
        )
        by_id = {r.requirement_id: r.strength for r in results}
        assert by_id[first.id] == 0.0
        assert by_id[second.id] == 1.0

    def test_a_negative_verdict_carries_no_evidence(self) -> None:
        """Showing a resume line beside a "no" would point at text that supports
        nothing."""
        req = requirement("Python")
        candidate = Candidate(
            text="Built a Django service in Python",
            origin=SkillOrigin.EXPERIENCE_BULLET,
            span=span_for("Built a Django service in Python"),
        )
        results = to_adjudications(
            LlmAdjudication(verdicts=[LlmVerdict(requirement="Python", verdict="no")]),
            [(req, SemanticResult(req.id, candidate, 0.7))],
        )
        assert results[0].evidence is None

    def test_location_still_caps_what_a_judged_match_is_worth(self) -> None:
        """A yes on a skills-list entry is not worth more than a lexical match
        in the same place."""
        req = requirement("Docker")
        candidate = Candidate(
            text="Docker", origin=SkillOrigin.SKILLS_LIST, span=span_for("Docker")
        )
        results = to_adjudications(
            LlmAdjudication(verdicts=[LlmVerdict(requirement="Docker", verdict="yes")]),
            [(req, SemanticResult(req.id, candidate, 0.7))],
        )
        assert results[0].strength == 0.5


class TestFullPipeline:
    """What each tier costs is the point of the whole design."""

    async def test_a_fully_matched_job_costs_nothing(self) -> None:
        client, provider = make_client()
        document = make_document()
        index = build_index(document, RESUME_TEXT)

        job = JobTarget(
            requirements=[
                requirement("Python", category=RequirementCategory.HARD_SKILL),
                requirement("Docker", category=RequirementCategory.HARD_SKILL),
            ]
        )
        report, stats = await match(
            client=client,
            job=job,
            document=document,
            index=index,
            resume_text=RESUME_TEXT,
        )

        assert provider.embed_batches == []
        assert provider.prompts == []
        assert stats.deterministic == 2
        assert stats.free_share == 1.0
        assert len(report.matches) == 2

    async def test_an_unmatched_requirement_reaches_the_semantic_tier(self) -> None:
        vector = [1.0, 0.0, 0.0]
        client, provider = make_client(
            embedding={
                "Comfortable presenting to non-technical audiences": vector,
                "Presented quarterly findings to the merchandising team": vector,
            }
        )
        document = make_document()
        job = JobTarget(
            requirements=[requirement("Comfortable presenting to non-technical audiences")]
        )

        report, stats = await match(
            client=client,
            job=job,
            document=document,
            index=build_index(document, RESUME_TEXT),
            resume_text=RESUME_TEXT,
        )

        assert stats.embedding_calls == 1
        assert stats.semantic == 1
        assert provider.prompts == []  # never reached adjudication
        assert report.matches[0].status is not MatchStatus.MISSING

    async def test_the_ambiguous_band_costs_exactly_one_model_call(self) -> None:
        # cos([1,1,0], [1,0,0]) = 0.707, which lands inside the ambiguous band
        # and so requires adjudication.
        client, provider = make_client(
            responses=[
                '{"verdicts": [{"requirement": "Exposure to container tooling",'
                ' "verdict": "partial", "reason": "Docker is listed"}]}'
            ],
            embedding={
                "Exposure to container tooling": [1.0, 1.0, 0.0],
                "Presented quarterly findings to the merchandising team": [1.0, 0.0, 0.0],
                "Built a Django service in Python": [1.0, 0.0, 0.0],
            },
        )
        document = make_document()
        job = JobTarget(requirements=[requirement("Exposure to container tooling")])

        _, stats = await match(
            client=client,
            job=job,
            document=document,
            index=build_index(document, RESUME_TEXT),
            resume_text=RESUME_TEXT,
        )

        assert stats.embedding_calls == 1
        assert stats.llm_calls == 1
        assert len(provider.prompts) == 1

    async def test_the_whole_match_stays_within_two_requests(self) -> None:
        """Two paid requests total, however many requirements there are."""
        client, provider = make_client(
            responses=['{"verdicts": []}'],
            embedding={},
        )
        document = make_document()
        job = JobTarget(
            requirements=[requirement(f"Unmatched requirement number {n}") for n in range(20)]
        )

        _, stats = await match(
            client=client,
            job=job,
            document=document,
            index=build_index(document, RESUME_TEXT),
            resume_text=RESUME_TEXT,
        )

        assert stats.embedding_calls <= 1
        assert stats.llm_calls <= 1
        assert len(provider.embed_batches) <= 1

    async def test_the_analysis_budget_is_respected(self) -> None:
        client, _ = make_client(
            responses=['{"verdicts": []}'],
            embedding={},
        )
        document = make_document()
        budget = AnalysisBudget(max_calls=6)

        await match(
            client=client,
            job=JobTarget(requirements=[requirement("Something unmatched entirely")]),
            document=document,
            index=build_index(document, RESUME_TEXT),
            resume_text=RESUME_TEXT,
            analysis_budget=budget,
        )
        assert budget.used <= 2

    async def test_statistics_account_for_every_requirement(self) -> None:
        client, _ = make_client(responses=['{"verdicts": []}'], embedding={})
        document = make_document()
        job = JobTarget(
            requirements=[
                requirement("Python", category=RequirementCategory.HARD_SKILL),
                requirement("Something unmatched entirely"),
            ]
        )

        _, stats = await match(
            client=client,
            job=job,
            document=document,
            index=build_index(document, RESUME_TEXT),
            resume_text=RESUME_TEXT,
        )

        assert stats.total == 2
        assert stats.deterministic + stats.semantic + stats.adjudicated + stats.unresolved == 2


class TestCandidateBuilding:
    def test_bullets_become_candidates(self) -> None:
        candidates = build_candidates(make_document(), RESUME_TEXT)
        assert any("Presented quarterly" in c.text for c in candidates)

    def test_candidates_keep_their_origin(self) -> None:
        """Origin is what decides the strength of a semantic match."""
        candidates = build_candidates(make_document(), RESUME_TEXT)
        assert all(c.origin is SkillOrigin.EXPERIENCE_BULLET for c in candidates)

    def test_very_short_text_is_not_a_candidate(self) -> None:
        document = ResumeDocument(
            experience=[ExperienceItem(title="x", bullets=[Bullet(text="Hi", span=None)])]
        )
        assert build_candidates(document, "Hi") == []

    def test_stats_default_to_zero(self) -> None:
        assert MatchStats().free_share == 0.0
