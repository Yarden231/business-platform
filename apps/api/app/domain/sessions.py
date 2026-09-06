"""When a session stops being usable (docs/security.md §3).

Four independent reasons, expressed as one pure function over the row's
timestamps so that "is this session still valid?" has a single answer and can be
unit tested at the boundaries — one second either side of an expiry — without a
database, a request or a clock that has to be waited out.

The server-side row is authoritative. Cookie expiry is a hint to the browser
and is never consulted here: a cookie that outlives its session must fail, and a
session that outlives its cookie is simply unreachable.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum


class SessionInvalidity(StrEnum):
    """Why a session may not be used. `None` from `session_invalidity` means it may."""

    #: Logout, password change, admin reset or deactivation set `revoked_at`.
    #: Checked first, because revocation has to beat every other consideration:
    #: it is the control incident response depends on (ADR-0004).
    REVOKED = "REVOKED"
    #: The absolute cap has passed. A session cannot be kept alive forever by
    #: using it.
    EXPIRED = "EXPIRED"
    #: Unused for longer than the idle window.
    IDLE_TIMEOUT = "IDLE_TIMEOUT"


def session_invalidity(
    *,
    last_seen_at: datetime,
    expires_at: datetime,
    revoked_at: datetime | None,
    now: datetime,
    idle_timeout_seconds: int,
) -> SessionInvalidity | None:
    """Why this session may not be used right now, or `None` if it may."""
    if revoked_at is not None:
        return SessionInvalidity.REVOKED
    if now >= expires_at:
        return SessionInvalidity.EXPIRED
    if now - last_seen_at >= timedelta(seconds=idle_timeout_seconds):
        return SessionInvalidity.IDLE_TIMEOUT
    return None


def last_seen_refresh_is_due(
    *, last_seen_at: datetime, now: datetime, refresh_interval_seconds: int
) -> bool:
    """Whether the idle clock is stale enough to be worth a write.

    Without this the idle timeout would cost an `UPDATE` on every authenticated
    request, including reads. The cost of throttling it is that the effective
    idle window is the configured one plus up to one refresh interval, which is
    a documented and deliberate trade (docs/security.md §3).
    """
    return now - last_seen_at >= timedelta(seconds=refresh_interval_seconds)
