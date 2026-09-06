"""Turning exceptions into the one error envelope (docs/api.md §2).

Three rules govern everything here:

1. every non-2xx response has the same shape, including the ones FastAPI and
   Starlette raise on their own;
2. nothing internal escapes — no stack trace, no SQL, no driver text, no
   exception message from an unexpected failure, no configuration value;
3. the `request_id` in the body matches the `X-Request-ID` header and the log
   line, which is how a support question is answered without disclosing any of
   the above.
"""

from __future__ import annotations

from typing import Final

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.middleware import REQUEST_ID_HEADER, SECURITY_HEADERS
from app.core.errors import AppError, ErrorCode, ErrorDetail
from app.core.logging import get_logger
from app.core.request_context import get_request_id
from app.schemas.errors import ErrorBody, ErrorDetailModel, ErrorEnvelope

logger = get_logger(__name__)

_UNKNOWN_REQUEST_ID: Final = "unknown"

#: Framework-raised HTTP errors get a code and a message of our own. The
#: exception's own `detail` is discarded on purpose: it is written by whichever
#: library raised it and is not part of the contract.
_STATUS_CODES: Final[dict[int, tuple[ErrorCode, str]]] = {
    400: (ErrorCode.BAD_REQUEST, "The request was malformed."),
    404: (ErrorCode.NOT_FOUND, "The requested resource does not exist."),
    405: (ErrorCode.METHOD_NOT_ALLOWED, "That method is not allowed on this resource."),
    409: (ErrorCode.CONFLICT, "The request conflicts with the current state of the resource."),
    422: (ErrorCode.VALIDATION_ERROR, "The request failed validation."),
    503: (ErrorCode.SERVICE_UNAVAILABLE, "The service is temporarily unavailable."),
}


def error_response(
    *,
    status_code: int,
    code: ErrorCode,
    message: str,
    details: list[ErrorDetail] | None = None,
) -> JSONResponse:
    """Build the envelope, with the request id and the security headers attached.

    The headers are set here as well as in the middleware because an unhandled
    exception is rendered outside the middleware stack, and a 500 must not be
    the one response in the system that is missing them.
    """
    request_id = get_request_id() or _UNKNOWN_REQUEST_ID
    envelope = ErrorEnvelope(
        error=ErrorBody(
            code=code,
            message=message,
            details=[ErrorDetailModel(field=d.field, issue=d.issue) for d in details or []],
            request_id=request_id,
        )
    )
    return JSONResponse(
        status_code=status_code,
        content=envelope.model_dump(mode="json"),
        headers={**SECURITY_HEADERS, REQUEST_ID_HEADER: request_id},
    )


async def handle_app_error(_request: Request, exc: Exception) -> JSONResponse:
    """An error the application raised deliberately; its message is part of the contract."""
    assert isinstance(exc, AppError)  # noqa: S101 - registered for this type only
    return error_response(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        details=exc.details,
    )


async def handle_request_validation_error(_request: Request, exc: Exception) -> JSONResponse:
    """Field-level validation, reported per field.

    Only the location and the failure *type* are returned. Pydantic's `input`
    and `msg` are omitted deliberately: echoing the rejected value back would
    put a password or an ID number into an error body and, from there, into
    whatever logs it.
    """
    assert isinstance(exc, RequestValidationError)  # noqa: S101 - registered for this type only
    details = [
        ErrorDetail(
            field=".".join(str(part) for part in error["loc"][1:]) or None,
            issue=str(error["type"]),
        )
        for error in exc.errors()
    ]
    return error_response(
        status_code=422,
        code=ErrorCode.VALIDATION_ERROR,
        message="The request failed validation.",
        details=details,
    )


async def handle_http_exception(_request: Request, exc: Exception) -> JSONResponse:
    """`HTTPException` raised by the framework — unknown route, wrong method, and so on."""
    assert isinstance(exc, StarletteHTTPException)  # noqa: S101 - registered for this type only
    code, message = _STATUS_CODES.get(
        exc.status_code,
        (ErrorCode.BAD_REQUEST, "The request could not be completed.")
        if exc.status_code < 500
        else (ErrorCode.INTERNAL_ERROR, "An unexpected error occurred."),
    )
    return error_response(status_code=exc.status_code, code=code, message=message, details=[])


async def handle_unexpected_error(_request: Request, exc: Exception) -> JSONResponse:
    """Anything we did not anticipate.

    The exception, with its traceback, goes to the log against this request's
    id. The caller gets a generic sentence and that id, and nothing else.
    """
    logger.error("unhandled_exception", error_type=type(exc).__name__, exc_info=exc)
    return error_response(
        status_code=500,
        code=ErrorCode.INTERNAL_ERROR,
        message="An unexpected error occurred.",
        details=[],
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, handle_app_error)
    app.add_exception_handler(RequestValidationError, handle_request_validation_error)
    app.add_exception_handler(StarletteHTTPException, handle_http_exception)
    app.add_exception_handler(Exception, handle_unexpected_error)
