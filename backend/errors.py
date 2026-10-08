# backend/errors.py
"""Uniform REST errors (contract section 11). Owner: Coder 3.
Raise AppError anywhere in a route; every non-2xx response gets the 11.1 body."""
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from schemas import ErrorCode, ErrorDetail, ErrorResponse

log = logging.getLogger("vision_assistant")

# Contract 11.2. Codes not listed here (WebSocket-only ones) fall back to 500.
ERROR_STATUS: dict[ErrorCode, int] = {
    "VALIDATION_ERROR": 422,
    "INVALID_FRAME": 400,
    "USER_NOT_FOUND": 404,
    "SESSION_NOT_FOUND": 404,
    "ALERT_NOT_FOUND": 404,
    "INVALID_STATUS_TRANSITION": 409,
    "NO_RECENT_FRAME": 409,
    "DESTINATION_NOT_FOUND": 404,
    "MODEL_NOT_READY": 503,
    "PIPELINE_ERROR": 500,
    "INTERNAL": 500,
    "NOT_FOUND": 404,
    "METHOD_NOT_ALLOWED": 405,
    "BAD_REQUEST": 400,
}


class AppError(Exception):
    """e.g. raise AppError("SESSION_NOT_FOUND", f"Session {session_id} does not exist or has ended.")"""

    def __init__(self, code: ErrorCode, message: str, status: int | None = None,
                 details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status or ERROR_STATUS.get(code, 500)
        self.details = details or {}


def error_response(status: int, code: ErrorCode, message: str, details: dict[str, Any] | None = None) -> JSONResponse:
    body = ErrorResponse(error=ErrorDetail(code=code, message=message, details=details or {}))
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"))


def _http_code(status: int) -> ErrorCode:
    if status == 404:
        return "NOT_FOUND"
    if status == 405:
        return "METHOD_NOT_ALLOWED"
    return "INTERNAL" if status >= 500 else "BAD_REQUEST"


def install_error_handlers(app: FastAPI) -> None:
    """Call before adding CORSMiddleware, so CORS wraps the 500 handler too."""

    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return error_response(exc.status, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Drop "input" (can echo a whole base64 image or a secret) and "ctx" (may not be JSON-safe).
        errors = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
        return error_response(422, "VALIDATION_ERROR", "Request validation failed.", {"errors": errors})

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return error_response(exc.status_code, _http_code(exc.status_code), str(exc.detail))

    # A middleware, not exception_handler(Exception): Starlette runs that one outside CORS,
    # so the browser would see a CORS failure instead of this body.
    @app.middleware("http")
    async def _unhandled_error(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        try:
            return await call_next(request)
        except Exception:
            log.exception("Unhandled error on %s %s", request.method, request.url.path)
            return error_response(500, "INTERNAL", "Internal server error.")
