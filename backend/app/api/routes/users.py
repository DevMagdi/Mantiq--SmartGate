"""User account administration (admin only)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from app.api.deps import AdminUser, PaginationDep, SessionDep
from app.models.enums import UserRole
from app.schemas.auth import AdminPasswordReset, UserCreate, UserRead, UserUpdate
from app.schemas.common import Message, Page
from app.services.user_service import user_service

router = APIRouter(prefix="/users", tags=["Users"], dependencies=[])


@router.get("", response_model=Page[UserRead], summary="List users")
async def list_users(
    session: SessionDep,
    admin: AdminUser,
    pagination: PaginationDep,
    compound_id: uuid.UUID | None = Query(default=None),
    role: UserRole | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    search: str | None = Query(default=None, max_length=120),
) -> Page[UserRead]:
    page = await user_service.list(
        session,
        pagination.to_params(),
        compound_id=compound_id,
        role=role,
        is_active=is_active,
        search=search,
    )
    return Page[UserRead].create(
        [UserRead.from_user(item) for item in page.items], page.total, page.page, page.page_size
    )


@router.post(
    "",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a user",
)
async def create_user(payload: UserCreate, session: SessionDep, admin: AdminUser) -> UserRead:
    user = await user_service.create(session, payload, actor=admin)
    return UserRead.from_user(user)


@router.get("/{user_id}", response_model=UserRead, summary="Get a user")
async def get_user(user_id: uuid.UUID, session: SessionDep, admin: AdminUser) -> UserRead:
    return UserRead.from_user(await user_service.get(session, user_id))


@router.patch("/{user_id}", response_model=UserRead, summary="Update a user")
async def update_user(
    user_id: uuid.UUID, payload: UserUpdate, session: SessionDep, admin: AdminUser
) -> UserRead:
    return UserRead.from_user(await user_service.update(session, user_id, payload))


@router.delete("/{user_id}", response_model=Message, summary="Deactivate a user")
async def delete_user(user_id: uuid.UUID, session: SessionDep, admin: AdminUser) -> Message:
    user = await user_service.deactivate(session, user_id, actor=admin)
    return Message(message=f"{user.full_name} has been deactivated")


@router.post("/{user_id}/reset-password", response_model=Message, summary="Reset a password")
async def reset_password(
    user_id: uuid.UUID, payload: AdminPasswordReset, session: SessionDep, admin: AdminUser
) -> Message:
    await user_service.reset_password(session, user_id, payload.new_password)
    return Message(message="Password reset successfully")
