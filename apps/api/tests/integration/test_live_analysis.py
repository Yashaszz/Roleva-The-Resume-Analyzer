"""One real analysis against a real model. Gate 5's criterion.

Everything else about the pipeline is proved offline against a fake provider,
which is the right way round: a suite that needs a network and a quota to run is
a suite that stops being run. But a fake provider cannot tell us whether Gemini
actually honours the schemas, whether the prompts produce sensible extraction,
or whether the whole thing fits inside the free tier's per-minute limit.

So this exists, runs against one synthetic resume, and is skipped without a key.
It costs about five requests of the daily allowance.

The resume is generated and fictional. No real person's data is sent anywhere by
this test.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from roleva.config import get_settings
from roleva.llm.budget import DailyBudget, InMemoryUsageStore
from roleva.llm.client import build_client
from roleva.models.report import AnalysisStatus
from roleva.orchestration.pipeline import AnalysisRequest, Pipeline

settings = get_settings()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.live,
    pytest.mark.skipif(
        not settings.gemini_api_key,
        reason="Live test: set GEMINI_API_KEY to run one real analysis",
    ),
]

FIXTURES = Path(__file__).parents[1] / "fixtures"


@pytest.mark.asyncio
async def test_a_real_analysis_completes(synthetic_resumes: Path) -> None:
    """The full pipeline against the real model, end to end."""
    resume = synthetic_resumes / "single-column-classic.pdf"
    job = (FIXTURES / "jds" / "backend-entry-years.txt").read_text(encoding="utf-8")

    # A fresh in-memory counter: this test should not consume the shared daily
    # budget's record, and it should not be blocked by it either.
    budget = DailyBudget(InMemoryUsageStore(), settings.llm_max_rpd)
    pipeline = Pipeline(client=build_client(settings, budget), settings=settings)

    outcome = await pipeline.run(
        AnalysisRequest(
            analysis_id=uuid.uuid4().hex,
            pdf_bytes=resume.read_bytes(),
            job_description=job,
            filename=resume.name,
        )
    )
    report = outcome.report

    assert report.status in {AnalysisStatus.COMPLETE, AnalysisStatus.PARTIAL}

    # --- the report is actually a report ---
    assert 0 < report.scores.overall.value <= 100
    assert report.verdict.strip()
    assert report.job.requirements, "no requirements were extracted from the posting"
    assert report.scores.job_match.components

    # --- the free-tier constraint the architecture is built around ---
    assert outcome.llm_calls <= 6, f"used {outcome.llm_calls} calls"

    # --- every quote still points at real text ---
    for match in report.matches.matches:
        for evidence in match.evidence:
            assert evidence.span.verify(outcome.resume_text), evidence.span.text

    # --- nothing the model wrote invented a fact ---
    from roleva.advice import grounding

    for suggestion in report.bullet_suggestions:
        result = grounding.check(original=suggestion.original, suggestion=suggestion.suggestion)
        assert result.grounded, f"{suggestion.suggestion} -> {result.summary}"

    # Printed so a live run says something useful about what it proved.
    print(
        f"\nlive: overall={report.scores.overall.value} "
        f"band={report.scores.overall.band.value} "
        f"requirements={len(report.job.requirements)} "
        f"calls={outcome.llm_calls} "
        f"model={pipeline.client.last_model_used} "
        f"degraded={[s.value for s in report.degraded_stages]} "
        f"ms={outcome.log.total_ms}"
    )
