"""Shared behaviour for the request and response models.

Requests forbid unknown fields (docs/security.md §5). Silently ignoring them is
how a client believes it changed something it did not — a renamed field that
still "works" in a `PATCH` is the version of this bug that loses data — and it
is also how a mass-assignment attempt goes unnoticed instead of being refused.

Responses do not need the same rule and deliberately do not get a permissive
base either: every response model in this codebase lists its fields explicitly
and is constructed from a service result, never from an ORM object, so a new
column cannot publish itself (docs/api.md §1).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class RequestModel(BaseModel):
    """Base for every request body. Rejects fields the endpoint does not define."""

    model_config = ConfigDict(extra="forbid")
