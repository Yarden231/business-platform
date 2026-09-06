"""The liveness endpoint, and what the API contract publishes."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import AsyncClient


@pytest.mark.parametrize("path", ["/healthz", "/api/v1/healthz"])
async def test_healthz_reports_ok(client: AsyncClient, path: str) -> None:
    response = await client.get(path)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_healthz_response_carries_nothing_beyond_status(client: AsyncClient) -> None:
    response = await client.get("/healthz")

    assert list(response.json()) == ["status"]


def test_openapi_publishes_the_versioned_probes_only(app: FastAPI) -> None:
    """The unversioned paths are infrastructure probes, so they stay out of the contract.

    `/api/v1/*` is what the web application calls, so it is published and will
    appear in the generated TypeScript types from Phase 3 onward.
    """
    paths = app.openapi()["paths"]

    assert "/api/v1/healthz" in paths
    assert "/api/v1/readyz" in paths
    assert "/healthz" not in paths
    assert "/readyz" not in paths
