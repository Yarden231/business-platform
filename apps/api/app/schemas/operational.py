"""Health and readiness payloads.

Both carry a single word. No version, environment, dependency name, hostname or
timing detail: these endpoints are unauthenticated, so anything they disclose is
disclosed to everyone (docs/api.md §5).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Liveness."""

    status: Literal["ok"] = "ok"


class ReadinessResponse(BaseModel):
    """Readiness: the dependencies needed to serve traffic answered."""

    status: Literal["ready"] = "ready"
