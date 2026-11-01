"""User account management (admin only)."""

from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import BadRequestError, ConflictError, NotFoundError, PermissionDeniedError
from app.core.security import hash_password
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.auth import UserCreate, UserUpdate
from app.services.pagination import PageParams, apply_sort, build_page, count_rows
from app.schemas.common import Page


class UserService:
    """CRUD operations for application users."""

    async def get(self, session: AsyncSession, user_id: uuid.UUID) -> User:
        stmt = select(User).where(User.id == user_id).options(selectinload(User.resident_profile))
        user = (await session.execute(stmt)).scalar_one_or_none()
        if user is None:
            raise NotFoundError("User not found", code="user_not_found")
        return user

    async def list(
        self,
        session: AsyncSession,
        params: PageParams,
        *,
        compound_id: uuid.UUID | None = None,
        role: UserRole | None = None,
        is_active: bool | None = None,
        search: str | None = None,
    ) -> Page[User]:
        stmt = select(User).options(selectinload(User.resident_profile))
        if compound_id is not None:
            stmt = stmt.where(User.compound_id == compound_id)
        if role is not None:
            stmt = stmt.where(User.role == role)
        if is_active is not None:
            stmt = stmt.where(User.is_active.is_(is_active))
        if search:
            term = f"%{search.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    User.full_name.ilike(term),
                    User.email.ilike(term),
                    User.phone.ilike(term),
                )
            )
        total = await count_rows(session, stmt)
        sort_columns = {"created_at": User.created_at, "full_name": User.full_name, "email": User.email}
        stmt = apply_sort(stmt, sort_columns.get(params.sort_by, User.created_at), params.sort_dir)
        stmt = stmt.offset(params.offset).limit(params.page_size)
        items = list((await session.execute(stmt)).scalars().unique().all())
        return build_page(items, total, params)

    async def create(self, session: AsyncSession, payload: UserCreate, *, actor: User) -> User:
        email = payload.email.lower()
        existing = await session.scalar(select(User).where(User.email == email))
        if existing is not None:
            raise ConflictError("A user with this email already exists", code="email_taken")
        if actor.role != UserRole.ADMIN and payload.compound_id != actor.compound_id:
            raise PermissionDeniedError("You can only create users in your compound")
        if payload.role != UserRole.ADMIN and payload.compound_id is None and actor.compound_id is None:
            raise BadRequestError("Non-admin users must be attached to a compound")
        user = User(
            email=email,
            hashed_password=hash_password(payload.password),
            full_name=payload.full_name.strip(),
            phone=payload.phone,
            role=payload.role,
            is_active=payload.is_active,
            compound_id=payload.compound_id or (None if actor.role == UserRole.ADMIN else actor.compound_id),
        )
        session.add(user)
        await session.commit()
        return await self.get(session, user.id)

    async def update(self, session: AsyncSession, user_id: uuid.UUID, payload: UserUpdate) -> User:
        user = await self.get(session, user_id)
        data = payload.model_dump(exclude_unset=True)
        if "email" in data and data["email"]:
            email = str(data["email"]).lower()
            clash = await session.scalar(
                select(User).where(User.email == email, User.id != user_id)
            )
            if clash is not None:
                raise ConflictError("A user with this email already exists", code="email_taken")
            user.email = email
        for field in ("full_name", "phone", "role", "is_active", "compound_id"):
            if field in data:
                setattr(user, field, data[field])
        if user.role != UserRole.ADMIN and user.compound_id is None:
            raise BadRequestError("Non-admin users must be attached to a compound")
        await session.commit()
        await session.refresh(user)
        return user

    async def deactivate(self, session: AsyncSession, user_id: uuid.UUID, *, actor: User) -> User:
        if user_id == actor.id:
            raise BadRequestError("You cannot deactivate your own account", code="self_deactivation")
        user = await self.get(session, user_id)
        user.is_active = False
        await session.commit()
        return user

    async def reset_password(
        self, session: AsyncSession, user_id: uuid.UUID, new_password: str
    ) -> None:
        user = await self.get(session, user_id)
        user.hashed_password = hash_password(new_password)
        user.failed_login_attempts = 0
        await session.commit()


user_service = UserService()
