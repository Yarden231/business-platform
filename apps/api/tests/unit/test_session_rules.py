"""Session validity and refresh throttling (docs/security.md §3).

`app.domain.sessions` is pure so that the four expiry rules can be tested one
second either side of each boundary, instead of by waiting out an eight-hour
idle window against a real database.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.sessions import (
    SessionInvalidity,
    last_seen_refresh_is_due,
    session_invalidity,
)

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
IDLE_SECONDS = 8 * 60 * 60


def invalidity(
    *,
    last_seen_at: datetime | None = None,
    expires_at: datetime | None = None,
    revoked_at: datetime | None = None,
    now: datetime = NOW,
) -> SessionInvalidity | None:
    """`session_invalidity` for a session that is valid unless an argument says otherwise."""
    return session_invalidity(
        last_seen_at=last_seen_at if last_seen_at is not None else now,
        expires_at=expires_at if expires_at is not None else now + timedelta(hours=1),
        revoked_at=revoked_at,
        now=now,
        idle_timeout_seconds=IDLE_SECONDS,
    )


class TestValidSessions:
    def test_a_fresh_session_is_valid(self) -> None:
        assert invalidity() is None

    def test_a_session_used_just_inside_the_idle_window_is_valid(self) -> None:
        assert invalidity(last_seen_at=NOW - timedelta(seconds=IDLE_SECONDS - 1)) is None

    def test_a_session_one_second_from_its_absolute_expiry_is_valid(self) -> None:
        assert invalidity(expires_at=NOW + timedelta(seconds=1)) is None


class TestRevocation:
    def test_a_revoked_session_is_invalid(self) -> None:
        assert invalidity(revoked_at=NOW - timedelta(minutes=1)) is SessionInvalidity.REVOKED

    def test_revocation_is_reported_ahead_of_expiry(self) -> None:
        """Revocation is the control incident response depends on, so it wins (ADR-0004)."""
        reason = invalidity(
            revoked_at=NOW - timedelta(minutes=1),
            expires_at=NOW - timedelta(hours=5),
            last_seen_at=NOW - timedelta(days=2),
        )

        assert reason is SessionInvalidity.REVOKED

    def test_a_revocation_timestamp_in_the_future_still_counts(self) -> None:
        """Nothing writes one, but clock skew between processes must not reopen a session."""
        assert invalidity(revoked_at=NOW + timedelta(minutes=1)) is SessionInvalidity.REVOKED


class TestAbsoluteExpiry:
    def test_a_session_at_its_expiry_instant_is_invalid(self) -> None:
        assert invalidity(expires_at=NOW) is SessionInvalidity.EXPIRED

    def test_a_session_past_its_expiry_is_invalid(self) -> None:
        assert invalidity(expires_at=NOW - timedelta(seconds=1)) is SessionInvalidity.EXPIRED

    def test_recent_activity_does_not_extend_the_absolute_cap(self) -> None:
        """The point of the absolute lifetime is that using a session cannot renew it."""
        assert invalidity(expires_at=NOW, last_seen_at=NOW) is SessionInvalidity.EXPIRED


class TestIdleExpiry:
    def test_a_session_idle_for_exactly_the_window_is_invalid(self) -> None:
        assert (
            invalidity(last_seen_at=NOW - timedelta(seconds=IDLE_SECONDS))
            is SessionInvalidity.IDLE_TIMEOUT
        )

    def test_a_session_idle_beyond_the_window_is_invalid(self) -> None:
        assert invalidity(last_seen_at=NOW - timedelta(days=3)) is SessionInvalidity.IDLE_TIMEOUT

    def test_expiry_is_reported_ahead_of_idleness(self) -> None:
        reason = invalidity(
            expires_at=NOW - timedelta(seconds=1), last_seen_at=NOW - timedelta(days=3)
        )

        assert reason is SessionInvalidity.EXPIRED


class TestRefreshThrottling:
    @pytest.mark.parametrize("elapsed", [0, 1, 59])
    def test_a_recently_touched_session_is_not_rewritten(self, elapsed: int) -> None:
        """Otherwise every authenticated read would cost an UPDATE."""
        assert (
            last_seen_refresh_is_due(
                last_seen_at=NOW - timedelta(seconds=elapsed),
                now=NOW,
                refresh_interval_seconds=60,
            )
            is False
        )

    @pytest.mark.parametrize("elapsed", [60, 61, 3600])
    def test_a_stale_session_is_rewritten(self, elapsed: int) -> None:
        assert (
            last_seen_refresh_is_due(
                last_seen_at=NOW - timedelta(seconds=elapsed),
                now=NOW,
                refresh_interval_seconds=60,
            )
            is True
        )
