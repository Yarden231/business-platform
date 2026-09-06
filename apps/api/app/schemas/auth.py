"""Request and response models for `/api/v1/auth` (docs/api.md §4)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from app.domain.enums import UserRole
from app.domain.passwords import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH
from app.schemas.base import RequestModel

_EMAIL_MAX_LENGTH = 320


class LoginRequest(RequestModel):
    """Credentials for `POST /api/v1/auth/login`.

    `email` is a plain string rather than `EmailStr`, and `password` is only
    length-bounded. That is deliberate: a field-level `422` for a malformed
    address would answer "no account could possibly exist here" while a
    well-formed unknown address gets a `401`, which is the user-enumeration
    difference the endpoint exists to avoid (docs/security.md §2). Anything
    syntactically wrong simply fails to match an identity and gets the same
    uniform failure.

    The upper bounds are there so an oversized body is rejected before it
    reaches an Argon2 verification, which is 64 MiB of work per call.
    """

    email: str = Field(min_length=1, max_length=_EMAIL_MAX_LENGTH)
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)


class PasswordChangeRequest(RequestModel):
    """Body for `POST /api/v1/auth/password`.

    `new_password` is bounded here and validated against the full policy in
    `app.domain.passwords`, which reports every violation at once as
    `PASSWORD_INVALID` details.
    """

    current_password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)


class CurrentUserResponse(BaseModel):
    """`GET /api/v1/auth/me` — the caller's own identity, and nothing else.

    Every field here is already known to the caller. There is no session id, no
    token, no hash, no CSRF value and no lockout state: this endpoint is read by
    the browser on every page load, and its job is to answer "who am I and may I
    proceed", not to describe the session.
    """

    id: uuid.UUID
    email: str
    full_name: str
    role: UserRole
    must_change_password: bool = Field(
        description=(
            "When true, only /auth/me, /auth/password and /auth/logout are usable; "
            "every other endpoint answers 403 PASSWORD_CHANGE_REQUIRED."
        )
    )
