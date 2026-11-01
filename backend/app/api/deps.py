"""FastAPI dependencies: database, authentication, pagination and scoping."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthenticationError, PermissionDeniedError
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.user import User
from app.services.auth_service import auth_service
from app.services.pagination import PageParams, page_params
from app.services.permissions import compound_scope, is_manager

bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token")

SessionDep = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> User:
    """Resolve the authenticated user from the Authorization header."""
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("Authentication required", code="missing_token")
    user, _ = await auth_service.resolve_token(session, credentials.credentials)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_manager_user(user: CurrentUser) -> User:
    """Allow only admins and security officers."""
    if not is_manager(user):
        raise PermissionDeniedError("This action requires an officer or admin role")
    return user


async def require_admin_user(user: CurrentUser) -> User:
    """Allow only administrators."""
    if user.role != UserRole.ADMIN:
        raise PermissionDeniedError("Administrator privileges are required")
    return user


ManagerUser = Annotated[User, Depends(require_manager_user)]
AdminUser = Annotated[User, Depends(require_admin_user)]


@dataclass(frozen=True, slots=True)
class Pagination:
    """Pagination + sorting query parameters."""

    page: int = Query(default=1, ge=1, le=100_000)
    page_size: int = Query(default=25, ge=1, le=200)
    sort_by: str = Query(default="created_at", max_length=40)
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$")

    def to_params(self) -> PageParams:
        return page_params(self.page, self.page_size, self.sort_dir, self.sort_by)


PaginationDep = Annotated[Pagination, Depends()]


def scoped_compound(
    user: CurrentUser,
    compound_id: Annotated[uuid.UUID | None, Query(description="Compound filter")] = None,
) -> uuid.UUID | None:
    """Resolve the compound filter for the current user."""
    return compound_scope(user, compound_id)


CompoundScope = Annotated[uuid.UUID | None, Depends(scoped_compound)]


def client_ip(request: Request) -> str:
    """Best-effort client IP (honours X-Forwarded-For from a trusted proxy)."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


ClientIP = Annotated[str, Depends(client_ip)]
