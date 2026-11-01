"""Exception handlers producing the consistent error envelope."""

from __future__ import annotations

import uuid

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import AppError
from app.core.logging import get_logger, request_id_var

logger = get_logger(__name__)


def _envelope(
    code: str,
    message: str,
    status_code: int,
    details: object = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details,
                "request_id": request_id_var.get(),
            }
        },
        headers=headers,
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register every handler on the application."""

    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        if exc.status_code >= 500:
            logger.error("Application error on %s: %s", request.url.path, exc.message)
        return _envelope(exc.code, exc.message, exc.status_code, exc.details, headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = [
            {
                "field": ".".join(str(part) for part in error.get("loc", [])[1:]),
                "message": error.get("msg", "Invalid value"),
                "type": error.get("type"),
            }
            for error in exc.errors()
        ]
        return _envelope(
            "validation_error",
            "The request payload is invalid",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            details,
        )

    @app.exception_handler(IntegrityError)
    async def _integrity_error(request: Request, exc: IntegrityError) -> JSONResponse:
        logger.warning("Database constraint violation on %s: %s", request.url.path, exc.orig)
        return _envelope(
            "conflict",
            "The operation conflicts with existing data",
            status.HTTP_409_CONFLICT,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {
            401: "authentication_error",
            403: "permission_denied",
            404: "not_found",
            405: "method_not_allowed",
            429: "rate_limited",
        }.get(exc.status_code, "http_error")
        message = exc.detail if isinstance(exc.detail, str) else "Request failed"
        return _envelope(code, message, exc.status_code, headers=getattr(exc, "headers", None))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        error_id = uuid.uuid4().hex
        logger.exception("Unhandled error [%s] on %s", error_id, request.url.path)
        return _envelope(
            "internal_error",
            "An unexpected error occurred. Please contact support with the request id.",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            {"error_id": error_id},
        )
