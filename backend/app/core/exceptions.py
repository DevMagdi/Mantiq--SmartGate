"""Domain exceptions mapped to consistent HTTP error responses."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for expected, user facing application errors."""

    status_code: int = 400
    code: str = "bad_request"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.details = details


class BadRequestError(AppError):
    """Invalid request payload or query."""

    status_code = 400
    code = "bad_request"


class AuthenticationError(AppError):
    """Missing or invalid credentials / token."""

    status_code = 401
    code = "authentication_error"


class PermissionDeniedError(AppError):
    """Authenticated user is not allowed to perform the action."""

    status_code = 403
    code = "permission_denied"


class NotFoundError(AppError):
    """Requested resource does not exist."""

    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    """Request conflicts with the current state of the resource."""

    status_code = 409
    code = "conflict"


class UnprocessableError(AppError):
    """Semantically invalid request that passes schema validation."""

    status_code = 422
    code = "unprocessable_entity"


class RateLimitError(AppError):
    """Too many requests."""

    status_code = 429
    code = "rate_limited"


class ServiceUnavailableError(AppError):
    """A dependent service (database, redis, model) is unavailable."""

    status_code = 503
    code = "service_unavailable"


class VisionEngineError(AppError):
    """Computer vision pipeline failure."""

    status_code = 422
    code = "vision_engine_error"
