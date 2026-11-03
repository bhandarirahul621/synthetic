"""One error format everywhere (PRD §9.1.5), with a ``request_id`` on every response.

Every error body looks like::

    {"error": {"type": "invalid_request", "code": "fk_target_missing",
               "message": "...", "param": "schema_id", "request_id": "req_91aB"}}

Messages are written by us and never include request bodies or source-data
values (FR15). For validation errors we report *where* the problem is (the
field path), not the value that was sent.
"""

from __future__ import annotations

import logging
import time
import traceback
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from synthetic.api.ids import new_id
from synthetic.errors import SyntheticError

log = logging.getLogger("synthetic.api")

_STATUS_TYPES = {
    400: "invalid_request", 401: "authentication_error", 403: "permission_error", 404: "not_found",
    405: "invalid_request", 409: "conflict", 413: "invalid_request", 422: "unprocessable",
    429: "rate_limit_error", 501: "not_implemented",
}


class APIError(SyntheticError):
    """An error with an explicit HTTP status, raised from route handlers."""

    def __init__(self, status: int, code: str, message: str, param: str | None = None,
                 type: str | None = None, headers: dict[str, str] | None = None):
        super().__init__(code, message, param)
        self.status = status
        self.type = type or _STATUS_TYPES.get(status, "api_error")
        self.headers = headers or {}


def error_body(request: Request, type_: str, code: str, message: str, param: str | None = None) -> dict:
    return {"error": {"type": type_, "code": code, "message": message, "param": param,
                      "request_id": getattr(request.state, "request_id", None)}}


def error_response(request: Request, status: int, type_: str, code: str, message: str,
                   param: str | None = None, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(error_body(request, type_, code, message, param), status_code=status,
                        headers=headers)


def _field_path(loc: tuple | list) -> str:
    parts = [str(p) for p in loc if p not in ("body", "query", "path", "header")]
    return ".".join(parts) or "body"


def install_error_handlers(app: FastAPI) -> None:
    """Register handlers so every error uses the §9.1.5 envelope."""

    @app.exception_handler(SyntheticError)
    async def _synthetic(request: Request, exc: SyntheticError) -> JSONResponse:
        headers = getattr(exc, "headers", None)
        return error_response(request, exc.status, exc.type, exc.code, exc.message, exc.param, headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        problems = []
        first_param = None
        for err in exc.errors()[:5]:
            path = _field_path(err.get("loc", ()))
            first_param = first_param or path
            # Only our own messages and the field path; never err["input"] (could be source data).
            problems.append(f"{path}: {err.get('msg', 'invalid value')}")
        message = "The request is invalid. " + "; ".join(problems) + "."
        return error_response(request, 400, "invalid_request", "validation_error", message, first_param)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        message = {404: "No such endpoint. See /docs for the list of endpoints.",
                   405: "This HTTP method is not allowed on this endpoint."}.get(exc.status_code,
                                                                                 "The request failed.")
        return error_response(request, exc.status_code, _STATUS_TYPES.get(exc.status_code, "api_error"),
                              code, message)

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        # Log the stack frames and the exception *type* only. Exception messages
        # can contain data values (e.g. pandas parse errors), so they are omitted.
        frames = "".join(traceback.format_tb(exc.__traceback__))
        log.error("unhandled error request_id=%s type=%s\n%s",
                  getattr(request.state, "request_id", None), type(exc).__name__, frames)
        return error_response(request, 500, "api_error", "internal_error",
                              "Something went wrong on our side. It is safe to retry with the same "
                              "Idempotency-Key.")


def _safe_path(path: str) -> str:
    """Signed download tokens are credentials: never write them to the log."""
    if path.startswith("/v1/files/"):
        return "/v1/files/[redacted]"
    return path


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assign a request ID, add rate-limit headers, and write one access-log line per request.

    The log line has method, path, status, duration and key ID: never query
    strings (download tokens), headers or bodies.
    """

    async def dispatch(self, request: Request, call_next: Any):
        request.state.request_id = new_id("req", 12)
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["Request-Id"] = request.state.request_id
        limit = getattr(request.state, "rate_limit", None)
        if limit is not None:
            response.headers["RateLimit-Limit"] = str(limit[0])
            response.headers["RateLimit-Remaining"] = str(limit[1])
            response.headers["RateLimit-Reset"] = str(limit[2])
        log.info("request method=%s path=%s status=%s duration_ms=%.1f request_id=%s key_id=%s",
                 request.method, _safe_path(request.url.path), response.status_code,
                 (time.perf_counter() - started) * 1000, request.state.request_id,
                 getattr(request.state, "key_id", None))
        return response
