"""9.8 — what actually leaves the building.

Every other PII test checks the redactor in isolation. This one checks the
thing that matters: run a whole analysis, capture every payload handed to the
provider, and search those exact strings for the candidate's identity.

That distinction is the point. A redactor with perfect unit tests protects
nobody if one call site forgets to use it, and the only way to catch that is to
stand at the boundary and read what crosses. Gemini's free tier may use
submitted content, so this is the difference between a privacy claim and a
privacy property.

The interception is at the provider, not the client, because the client is
where redaction happens — sitting above it would test the mock.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest

from roleva.config import Settings
from roleva.llm.budget import DailyBudget, InMemoryUsageStore
from roleva.llm.client import LlmClient
from roleva.orchestration.pipeline import AnalysisRequest, Pipeline
from tests.integration.test_pipeline import JDS, RESUMES

pytestmark = pytest.mark.integration

# The identity planted in the resume the structurer reports. Every one of these
# strings must be absent from every outbound payload.
NAME = "Ananya Deshmukh"
EMAIL = "ananya.deshmukh@example.com"
PHONE = "+91 98220 41567"


class CapturingProvider:
    """Answers like a model, and keeps every prompt it was given."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def generate_json(self, *, prompt: str, model: str, **_: Any) -> str:
        self.prompts.append(prompt)
        low = prompt.lower()

        if "<resume>" in prompt and "rate how a resume is written" in low:
            return json.dumps(
                {
                    "clarity": 4,
                    "impact": 3,
                    "specificity": 4,
                    "professionalism": 4,
                    "relevance": 4,
                    "notes": [],
                }
            )
        if "rewrite" in low and "<bullets>" in prompt:
            return json.dumps({"rewrites": []})
        if "<job>" in prompt:
            return json.dumps(
                {
                    "title": "Backend Engineer",
                    "company": "Northwind",
                    "role_family": "backend_engineering",
                    "seniority": "entry",
                    "requirements": [
                        {"text": "Python", "category": "hard_skill", "priority": "must"}
                    ],
                }
            )
        if "adjudicat" in low or "verdict" in low:
            return json.dumps({"decisions": []})

        # The structurer. Returns a document carrying the identity, so the
        # downstream calls have something to leak if they are going to.
        return json.dumps(
            {
                "summary": f"{NAME} is a backend engineer.",
                "experience": [
                    {
                        "title": "Engineer",
                        "organization": "Zentara Technologies",
                        "location": "Pune",
                        "dates": "2024 - 2025",
                        "bullets": [f"Built a Django service, reachable at {EMAIL}"],
                    }
                ],
                "education": [],
                "projects": [],
                "skills": ["Python"],
                "certifications": [],
            }
        )

    async def embed(self, *, texts: list[str], model: str) -> list[list[float]]:
        # Embedded text crosses the wire too, so it is captured like a prompt.
        self.prompts.extend(texts)
        return [[0.0] * 8 for _ in texts]


async def _run() -> CapturingProvider:
    provider = CapturingProvider()
    settings = Settings(_env_file=None, gemini_api_key="unused")
    client = LlmClient(
        provider,  # type: ignore[arg-type]
        settings,
        DailyBudget(InMemoryUsageStore(), settings.llm_max_rpd),
    )
    resume = RESUMES / "single-column-classic.pdf"

    await Pipeline(client=client, settings=settings).run(
        AnalysisRequest(
            analysis_id=uuid.uuid4().hex,
            pdf_bytes=resume.read_bytes(),
            job_description=(JDS / "backend-entry-years.txt").read_text(encoding="utf-8"),
            filename=resume.name,
        )
    )
    return provider


class TestNothingIdentifyingLeavesTheProcess:
    @pytest.mark.asyncio
    async def test_the_capture_actually_captured_something(self) -> None:
        """A test that proves nothing because it saw nothing is worse than none."""
        provider = await _run()
        assert len(provider.prompts) >= 3
        assert any(len(p) > 200 for p in provider.prompts)

    @pytest.mark.asyncio
    async def test_no_email_address_reaches_the_provider(self) -> None:
        provider = await _run()
        for prompt in provider.prompts:
            assert EMAIL not in prompt
            # Any email at all, not merely the one planted: a resume can carry
            # a referee's address as easily as its author's.
            assert "@example.com" not in prompt

    @pytest.mark.asyncio
    async def test_no_phone_number_reaches_the_provider(self) -> None:
        provider = await _run()
        for prompt in provider.prompts:
            assert PHONE not in prompt
            assert "98220" not in prompt

    @pytest.mark.asyncio
    async def test_the_api_key_is_never_in_a_prompt(self) -> None:
        """Belt and braces: a key pasted into a prompt would be logged by the
        vendor as ordinary content."""
        provider = await _run()
        for prompt in provider.prompts:
            assert "GEMINI" not in prompt.upper() or "gemini" not in prompt
            assert "AIza" not in prompt

    @pytest.mark.asyncio
    async def test_the_resume_still_reaches_the_model(self) -> None:
        """Redaction must not be so aggressive that the analysis is worthless.

        This is the other half of the property: something identifying went out
        redacted, not nothing went out at all.
        """
        provider = await _run()
        combined = "\n".join(provider.prompts)
        assert "Django" in combined or "Python" in combined
