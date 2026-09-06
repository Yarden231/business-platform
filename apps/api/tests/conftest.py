"""Fixtures shared by the whole suite.

Tests are split in two, and the split is about what they need rather than what
they assert:

* `tests/unit` — no database, no network. Settings, the error envelope, request
  ids, logging, security headers, and the routes that touch nothing.
* `tests/integration` — real PostgreSQL, schema built by `alembic upgrade head`.
  See `tests/integration/conftest.py`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.settings import get_settings
from app.main import create_app


@pytest.fixture(autouse=True)
def _isolated_settings() -> Iterator[None]:
    """Never let one test's environment leak into the next through the settings cache."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def app() -> FastAPI:
    """A fresh application, built from whatever the environment currently says."""
    return create_app()


def build_client(app: FastAPI, *, tls: bool = False) -> AsyncClient:
    """An HTTP client wired straight into the ASGI app, with no network or server.

    `raise_app_exceptions=False` because the application turns every exception
    into a response: intercepting them here would make the 500 path untestable
    and would say nothing about what a real caller receives. A test that expects
    success asserts a 2xx, so an unexpected failure still fails the test.

    `tls=True` gives an `https` base URL. Only the production-cookie tests need
    it, and they need it for a real reason: a client keeps a `Secure` cookie
    only if it arrived over `https`, so without this the browser-side half of
    that behaviour could not be exercised at all.
    """
    scheme = "https" if tls else "http"
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url=f"{scheme}://testserver",
    )


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with build_client(app) as async_client:
        yield async_client
