"""The error envelope every non-2xx response uses (docs/api.md §2)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ErrorDetailModel(BaseModel):
    """One field-level problem."""

    field: str | None = Field(
        default=None,
        description="Dotted path of the offending field, or null for a whole-request problem.",
    )
    issue: str = Field(description="Stable, machine-readable description of the problem.")


class ErrorBody(BaseModel):
    code: str = Field(description="Stable error code; the web app maps it to Hebrew copy.")
    message: str = Field(description="English, developer-facing. Never shown to an end user.")
    details: list[ErrorDetailModel] = Field(default_factory=list)
    request_id: str = Field(description="Matches the X-Request-ID header and the server log entry.")


class ErrorEnvelope(BaseModel):
    """The single shape of every API error."""

    error: ErrorBody
