"""Export the API schema, including domain models that no endpoint returns yet.

FastAPI's generated schema only contains models an endpoint actually references.
Early in the build that is almost nothing, so the frontend would get no useful
types until the last endpoint lands — exactly backwards, since the UI work needs
those shapes while the endpoints are still being written.

So the domain models are injected explicitly. They are the contract between the
two languages whether or not a route currently mentions them.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from pydantic import BaseModel

from roleva.main import app
from roleva.models import (
    AnalysisReport,
    AtsReport,
    JobTarget,
    MatchReport,
    ProgressEvent,
    ResumeDocument,
    ScoreReport,
)

#: Roots to export. Nested models come along automatically via $defs.
ROOTS: list[type[BaseModel]] = [
    AnalysisReport,
    ProgressEvent,
    ResumeDocument,
    JobTarget,
    MatchReport,
    AtsReport,
    ScoreReport,
]


def domain_schemas() -> dict[str, Any]:
    """Flatten every domain model into OpenAPI-style component schemas."""
    components: dict[str, Any] = {}

    for model in ROOTS:
        schema = model.model_json_schema(ref_template="#/components/schemas/{model}")
        # Nested models arrive under $defs; OpenAPI wants them alongside the root.
        components.update(schema.pop("$defs", {}))
        components[model.__name__] = schema

    return components


def main() -> None:
    schema = app.openapi()
    schema.setdefault("components", {}).setdefault("schemas", {}).update(domain_schemas())
    json.dump(schema, sys.stdout, indent=2)


if __name__ == "__main__":
    main()
