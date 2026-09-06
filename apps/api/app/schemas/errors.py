"""The error envelope every non-2xx response uses (docs/api.md §2)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.core.errors import ErrorCode


class ErrorDetailModel(BaseModel):
    """One field-level problem."""

    field: str | None = Field(
        default=None,
        description="Dotted path of the offending field, or null for a whole-request problem.",
    )
    issue: str = Field(description="Stable, machine-readable description of the problem.")


class ErrorBody(BaseModel):
    #: Typed as the enum rather than `str` so the published OpenAPI document
    #: carries the whole code list. The web application generates its types from
    #: that document (ADR-0017), which makes its Hebrew error mapper a
    #: `Record<ErrorCode, string>` — exhaustive at compile time. A code added
    #: here without a Hebrew message therefore breaks the web build, which is
    #: the check ADR-0014 asks for (ADR-0039).
    code: ErrorCode = Field(description="Stable error code; the web app maps it to Hebrew copy.")
    message: str = Field(description="English, developer-facing. Never shown to an end user.")
    details: list[ErrorDetailModel] = Field(default_factory=list)
    request_id: str = Field(description="Matches the X-Request-ID header and the server log entry.")


class ErrorEnvelope(BaseModel):
    """The single shape of every API error."""

    error: ErrorBody
