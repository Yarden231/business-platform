"""Per-IP login throttling (docs/security.md §2).

Two brute-force controls run side by side and answer different attacks. The
per-identity lockout in `password_provider` stops guessing at *one* account. This
stops one source from spraying many accounts, which no per-identity counter can
see.

**Where the counter lives.** In `activity_log`, as the `USER_LOGIN_FAILED` rows
of the trailing window. That is not a shortcut: an in-process dictionary is
wrong here for three separate reasons — it is lost on every deploy and restart,
it is per-instance so two API replicas each grant the full allowance, and it is
a memory-growth surface an unauthenticated caller controls. The audit trail is
durable, shared and already being written on exactly the event that needs
counting, so Release 1 needs neither a new table nor Redis
(§17 of the phase brief, ADR-0004's "no cache until it matters" reasoning).

**The limitation, stated plainly.** The address is whatever the ASGI server
reports as the peer. The browser reaches the API through the same-origin Next.js
proxy (ADR-0005), so unless the ASGI server is told to trust the proxy's
forwarded headers — `uvicorn --proxy-headers --forwarded-allow-ips=<ingress>`,
which is a deployment setting, not application code — every browser login
appears to come from one address and this control degrades from per-client to
per-proxy. That is why the threshold is deliberately generous and why the
per-identity lockout, which is unaffected, is the primary control. It is written
down in `docs/security.md` rather than left as a surprise.
"""

from __future__ import annotations

from datetime import timedelta

from app.audit.actions import AuditAction
from app.core.errors import TooManyRequestsError
from app.core.settings import Settings
from app.core.time import utc_now
from app.repositories.activity_log import ActivityLogRepository


class LoginThrottle:
    """Refuses further login attempts from an address that keeps failing."""

    def __init__(self, *, activity: ActivityLogRepository, settings: Settings) -> None:
        self._activity = activity
        self._settings = settings

    async def ensure_within_limit(self, ip_address: str | None) -> None:
        """Raise `429` when this address has exhausted its allowance.

        An unknown address is not throttled. The alternative — treating "no
        peer address" as one bucket — would let a single caller that suppresses
        it deny the endpoint to everybody, which is a worse failure than the one
        being prevented.
        """
        if ip_address is None:
            return

        since = utc_now() - timedelta(seconds=self._settings.login_ip_window_seconds)
        failures = await self._activity.count_by_action_and_ip(
            action=AuditAction.USER_LOGIN_FAILED.value,
            ip_address=ip_address,
            since=since,
        )
        if failures >= self._settings.login_ip_max_failed_attempts:
            raise TooManyRequestsError
