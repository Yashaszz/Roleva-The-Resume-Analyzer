"""Shared test fixtures."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
RESUME_DIR = FIXTURES / "resumes"

sys.path.insert(0, str(FIXTURES))


@pytest.fixture(scope="session", autouse=True)
def synthetic_resumes() -> Path:
    """Build the synthetic resume PDFs if they are not already present.

    The PDFs are generated rather than committed: several megabytes of binaries
    in git for files that are fully reproducible from a 400-line script is a bad
    trade, and it avoids any ambiguity about whether a checked-in resume holds
    real data.
    """
    from generate_resumes import GENERATORS, generate_all

    expected = {RESUME_DIR / name for name in GENERATORS}
    if not all(path.is_file() for path in expected):
        generate_all(RESUME_DIR)

    return RESUME_DIR
