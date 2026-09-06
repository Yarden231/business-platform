"""Authorization policy (docs/security.md §4).

Pure functions over an `AuthenticatedActor`, so every rule is unit testable
without a request and can be called from a router dependency *and* from a
service for defence in depth. Phase 2 needs two of the three mechanisms
described in `docs/architecture.md` §6:

* **role gates** — `ensure_role`, below;
* **query scoping** — actor-scoped repository methods, which arrive with the
  entities that need scoping.

Object policies (`ensure_can_view_case`, `ensure_can_edit_person`, …) belong to
the phases that introduce those objects. Nothing here anticipates them: an
`ensure_can_view_case` written before `cases` exists would be a guess.

The `role` column becomes a `user_roles` table when client and lawyer portals
arrive. Because every check in the application goes through this module, that
stays an additive migration plus one edit here.
"""

from __future__ import annotations

from app.core.errors import ForbiddenError, PasswordChangeRequiredError
from app.domain.actor import AuthenticatedActor
from app.domain.enums import UserRole


def has_role(actor: AuthenticatedActor, *allowed: UserRole) -> bool:
    """Whether `actor` holds any of `allowed`."""
    return actor.role in allowed


def ensure_role(actor: AuthenticatedActor, *allowed: UserRole) -> None:
    """Refuse the request unless `actor` holds one of `allowed`.

    `403`, not `404`: the caller is authenticated and the endpoint's existence
    is public in the API contract, so this is the "visible but not permitted"
    case (ADR-0021). Endpoints that must not confirm a *resource* exists answer
    `404` instead, which is a decision for the phase that owns the resource.
    """
    if not has_role(actor, *allowed):
        raise ForbiddenError


def ensure_password_rotated(actor: AuthenticatedActor) -> None:
    """Refuse the request while the actor still holds a temporary password (ADR-0026).

    Applied to every authenticated endpoint except the three an account needs in
    order to escape this state: `GET /auth/me`, `POST /auth/password` and
    `POST /auth/logout`. Those three opt out explicitly, by depending on the
    actor without this gate, so adding an endpoint gates it by default — the
    safe direction for a mistake to fall in.
    """
    if actor.must_change_password:
        raise PasswordChangeRequiredError
