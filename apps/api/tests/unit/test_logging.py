"""Structured logging.

What matters operationally is that a log line is machine-readable, carries the
request id that the caller was given, and never carries a credential.
"""

from __future__ import annotations

import json

import pytest

from app.core.logging import get_logger
from app.main import create_app
from tests.conftest import build_client
from tests.support.logs import LogReader, capture_json_logs


@pytest.fixture
def json_logs(monkeypatch: pytest.MonkeyPatch) -> LogReader:
    """Configure the real JSON pipeline and hand back a reader for what it emitted."""
    return capture_json_logs(monkeypatch)


def test_a_log_line_is_json_with_the_expected_fields(json_logs: LogReader) -> None:
    get_logger("test").info("something_happened", detail="value")

    (entry,) = json_logs()
    assert entry["event"] == "something_happened"
    assert entry["detail"] == "value"
    assert entry["level"] == "info"
    assert entry["logger"] == "test"
    assert entry["timestamp"].endswith("Z")


def test_sensitive_keys_are_redacted_even_when_a_call_site_passes_them(
    json_logs: LogReader,
) -> None:
    get_logger("test").info(
        "login_attempt",
        password="hunter2",
        session_token="abc",
        csrf_token="def",
        database_url="postgresql://user:pw@host/db",
        email="staff@example.com",
    )

    (entry,) = json_logs()
    assert entry["password"] == "[redacted]"
    assert entry["session_token"] == "[redacted]"
    assert entry["csrf_token"] == "[redacted]"
    assert entry["database_url"] == "[redacted]"
    # Not everything is a secret; the redaction list is deliberately short.
    assert entry["email"] == "staff@example.com"


async def test_every_request_produces_one_access_log_line(json_logs: LogReader) -> None:
    async with build_client(create_app()) as client:
        response = await client.get("/api/v1/healthz")

    (entry,) = [line for line in json_logs() if line["event"] == "http_request"]
    assert entry["method"] == "GET"
    assert entry["route"] == "/api/v1/healthz"
    assert entry["status_code"] == 200
    assert isinstance(entry["duration_ms"], float)
    assert entry["request_id"] == response.headers["x-request-id"]


async def test_the_access_log_records_the_route_template_not_the_query_string(
    json_logs: LogReader,
) -> None:
    """From Phase 4 a query string carries search terms over personal data."""
    async with build_client(create_app()) as client:
        await client.get("/api/v1/healthz", params={"q": "123456789"})

    (entry,) = [line for line in json_logs() if line["event"] == "http_request"]
    assert entry["route"] == "/api/v1/healthz"
    assert "123456789" not in json.dumps(entry)
