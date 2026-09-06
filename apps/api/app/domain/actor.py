"""Who is making the request.

`AuthenticatedActor` is the only representation of the caller that leaves the
authentication layer. Session rows and `User` ORM instances stop at the service
boundary, which is what stops a router — or, later, an authorization policy —
from reaching a lazily-loaded relationship or a token hash it has no business
seeing.

It is a frozen dataclass in the pure domain layer so that policies
(`app.auth.policies`) are functions over a value object, testable with no
database and no request.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.domain.enums import UserRole


@dataclass(frozen=True, slots=True)
class AuthenticatedActor:
    """A staff member with a live session.

    Every field is already public to this caller: it is their own identity, and
    it is exactly what `GET /api/v1/auth/me` returns. There is no credential,
    no session token and no hash here.
    """

    id: uuid.UUID
    email: str
    full_name: str
    role: UserRole
    must_change_password: bool

    @property
    def is_admin(self) -> bool:
        return self.role is UserRole.ADMIN
