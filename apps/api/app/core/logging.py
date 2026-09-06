"""Structured application logging.

`structlog` renders every log line — the application's own and anything the
standard library or uvicorn emits — through one pipeline, so a log aggregator
sees a single shape. JSON in production, a readable console renderer on a
developer machine; the event dictionary is identical either way, so a field
that exists locally exists in production.

Application logs are operational telemetry. They are never the business audit
trail — that is `activity_log`, written transactionally (ADR-0010).
"""

from __future__ import annotations

import logging
from typing import Any, Final

import structlog

from app.core.settings import LogFormat, Settings

#: Keys that must never reach a log sink, whatever a call site passes. This is a
#: safety net rather than a licence to pass secrets: the rule is still "do not
#: log credentials, tokens or personal identifiers" (docs/security.md §7).
_REDACTED_KEYS: Final = frozenset(
    {
        "authorization",
        "cookie",
        "csrf_token",
        "database_url",
        "id_number",
        "password",
        "secret",
        "session_secret",
        "session_token",
        "set-cookie",
        "token",
    }
)
_REDACTED: Final = "[redacted]"


def _redact_sensitive(
    _logger: Any,  # noqa: ANN401 - structlog's processor signature
    _method_name: str,
    event_dict: structlog.typing.EventDict,
) -> structlog.typing.EventDict:
    for key in event_dict:
        if key.lower() in _REDACTED_KEYS:
            event_dict[key] = _REDACTED
    return event_dict


def _shared_processors() -> list[structlog.typing.Processor]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        _redact_sensitive,
    ]


def configure_logging(settings: Settings) -> None:
    """Install the logging pipeline. Idempotent, so tests may call it repeatedly."""
    shared = _shared_processors()
    json_output = settings.resolved_log_format is LogFormat.JSON

    renderers: list[structlog.typing.Processor] = [
        structlog.stdlib.ProcessorFormatter.remove_processors_meta
    ]
    if json_output:
        # ConsoleRenderer formats exceptions itself; JSONRenderer needs them
        # flattened into the event dictionary first.
        renderers.append(structlog.processors.format_exc_info)
        renderers.append(structlog.processors.JSONRenderer())
    else:
        renderers.append(structlog.dev.ConsoleRenderer(colors=False))

    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    root = logging.getLogger()
    # Reconfiguring reuses the sink already installed rather than binding
    # `sys.stderr` again, so repeated calls neither accumulate handlers nor
    # steal the stream back from a caller that redirected it. The exact-type
    # check keeps foreign handlers (pytest's log capture, for one) out of it.
    handler = (
        next(
            (existing for existing in root.handlers if type(existing) is logging.StreamHandler),
            None,
        )
        or logging.StreamHandler()
    )
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            # Records that never went through structlog (uvicorn, SQLAlchemy,
            # third-party libraries) are given the same fields.
            foreign_pre_chain=shared,
            processors=renderers,
        )
    )
    root.handlers = [handler]
    root.setLevel(settings.api_log_level)

    # uvicorn installs its own handlers; let its records propagate to ours
    # instead so there is exactly one renderer in the process.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """A bound logger. Use the module's `__name__` so `logger` identifies the source."""
    return structlog.stdlib.get_logger(name)
