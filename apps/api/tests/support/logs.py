"""Reading back what the logging pipeline actually emitted.

Asserting on log output needs care: neither `capsys` nor `capfd` sees these
lines, because the handler is installed once at configuration time and holds
its own stream. A test that reached for those fixtures would assert against an
empty string and pass no matter what was logged — which, for tests whose whole
job is "no credential appears in the log", would be worse than having no tests.

So the real handler is pointed at memory and its output is parsed back. That
also means these tests exercise the redaction processors rather than
side-stepping them.
"""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Callable
from typing import Any

import pytest

from app.core.logging import configure_logging
from app.core.settings import get_settings

#: Reads back everything the pipeline has emitted so far in the current test.
type LogReader = Callable[[], list[dict[str, Any]]]


def capture_json_logs(monkeypatch: pytest.MonkeyPatch) -> LogReader:
    """Configure the JSON pipeline into a buffer and return a reader over it.

    Reconfiguring keeps the same handler instance, so an application built
    inside the test writes here too.
    """
    monkeypatch.setenv("LOG_FORMAT", "json")
    get_settings.cache_clear()
    configure_logging(get_settings())

    buffer = io.StringIO()
    handler = next(h for h in logging.getLogger().handlers if type(h) is logging.StreamHandler)
    handler.setStream(buffer)

    def emitted() -> list[dict[str, Any]]:
        return [json.loads(line) for line in buffer.getvalue().splitlines() if line.startswith("{")]

    return emitted


def rendered(reader: LogReader) -> str:
    """Every emitted record as one searchable string, keys included.

    Searching the rendered JSON rather than named fields is deliberate: a leak
    would arrive in whatever field its author invented, so a test that only
    checked the fields it knew about would not find it.
    """
    return json.dumps(reader())
