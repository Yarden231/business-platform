"""Request correlation ids."""

from __future__ import annotations

from uuid import UUID

from httpx import AsyncClient


async def test_every_response_carries_a_request_id(client: AsyncClient) -> None:
    response = await client.get("/healthz")

    UUID(response.headers["x-request-id"])


async def test_two_requests_get_two_ids(client: AsyncClient) -> None:
    first = await client.get("/healthz")
    second = await client.get("/healthz")

    assert first.headers["x-request-id"] != second.headers["x-request-id"]


async def test_a_client_supplied_request_id_is_ignored(client: AsyncClient) -> None:
    """ADR-0032: a caller cannot choose the id the server logs and audits under."""
    supplied = "../../etc/passwd or any other text a caller fancies"

    response = await client.get("/healthz", headers={"X-Request-ID": supplied})

    assert response.headers["x-request-id"] != supplied
    UUID(response.headers["x-request-id"])
