"""Liveness and readiness.

Both are unauthenticated and both answer with one word, because everything an
unauthenticated endpoint says it says to the internet. The distinction between
them is the whole point:

* `/healthz` — is this process running? It touches nothing, so a database
  outage never gets the container killed and restarted, which would turn a
  recoverable dependency failure into a crash loop.
* `/readyz` — can this process serve traffic? It checks the dependencies a
  request actually needs, so an instance that cannot reach PostgreSQL is taken
  out of rotation while it stays alive and keeps retrying.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.dependencies import DbSession
from app.core.errors import ServiceUnavailableError
from app.core.logging import get_logger
from app.core.settings import get_settings
from app.db.health import check_database
from app.schemas.errors import ErrorEnvelope
from app.schemas.operational import HealthResponse, ReadinessResponse

logger = get_logger(__name__)

router = APIRouter(tags=["operational"])


@router.get("/healthz", summary="Liveness probe")
async def healthz() -> HealthResponse:
    """Report that the process is alive. Touches no dependency, by design."""
    return HealthResponse()


@router.get(
    "/readyz",
    summary="Readiness probe",
    responses={503: {"model": ErrorEnvelope, "description": "A dependency is unavailable."}},
)
async def readyz(session: DbSession) -> ReadinessResponse:
    """Report that the dependencies needed to serve traffic are available.

    PostgreSQL is the only one in Phase 1 — it is the only dependency a request
    currently has. Blob storage joins it in Phase 6, when there is an adapter to
    ask.
    """
    try:
        await check_database(session, timeout_seconds=get_settings().db_connect_timeout_seconds)
    except Exception as exc:
        # The reason goes to the log, where an operator can read it. The
        # response says only that the service is not ready: hostnames,
        # credentials and driver messages are not public information.
        logger.warning(
            "readiness_check_failed", dependency="database", error_type=type(exc).__name__
        )
        raise ServiceUnavailableError from exc
    return ReadinessResponse()
