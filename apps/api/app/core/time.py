"""Time helpers.

Every instant in this system is timezone-aware and stored in UTC
(ADR-0015). Business dates — deadlines, appointment and separation dates —
are calendar days and arrive with the entities that own them in later phases.
"""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    """The current instant, timezone-aware, in UTC."""
    return datetime.now(UTC)
