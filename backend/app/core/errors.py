"""Uniform API error contract.

Every error response is {"error": {"code", "message", "details"}, "requestId"}.
Domain handlers raise SentinelError; handlers translate it and unhandled
exceptions into the same shape. Internal exception text is never leaked.
"""

import logging
import uuid
from contextlib import contextmanager
from contextvars import ContextVar

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
logger = logging.getLogger("sentinel")


class SentinelError(Exception):
    status_code = 400

    def __init__(self, code: str, message: str, status_code: int | None = None, details: dict | None = None):
        self.code = code
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


def error_response(status_code: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details or {}}, "requestId": request_id_var.get()},
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(SentinelError)
    async def sentinel_error_handler(request: Request, exc: SentinelError):
        return error_response(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        errors = [
            {"field": ".".join(str(p) for p in e.get("loc", [])[1:]), "message": e.get("msg", "")}
            for e in exc.errors()
        ]
        return error_response(400, "VALIDATION_ERROR", "Request validation failed", {"errors": errors})

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception):
        logger.exception("Unhandled error: %s", exc)
        return error_response(500, "INTERNAL_ERROR", "An unexpected error occurred")


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request_id_var.set(rid)
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response


@contextmanager
def current_request_id(rid: str):
    """Bind an explicit request id (used by audit service)."""
    token = request_id_var.set(rid)
    try:
        yield
    finally:
        request_id_var.reset(token)
