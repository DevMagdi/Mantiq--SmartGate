"""Authentication, token issuance and password management."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.cache import get_cache
from app.core.config import settings
from app.core.exceptions import (
    AuthenticationError,
    BadRequestError,
    RateLimitError,
)
from app.core.logging import get_logger
from app.core.security import (
    TokenPayload,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    needs_rehash,
    verify_password,
)
from app.models.user import User

logger = get_logger(__name__)

_LOGIN_WINDOW_SECONDS = 900
_LOCK_THRESHOLD = settings.MAX_LOGIN_ATTEMPTS


class AuthService:
    """Stateless authentication service."""

    @staticmethod
    async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
        stmt = (
            select(User)
            .where(User.email == email.strip().lower())
            .options(selectinload(User.resident_profile))
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    @staticmethod
    async def get_user_by_id(session: AsyncSession, user_id: uuid.UUID) -> User | None:
        stmt = select(User).where(User.id == user_id).options(selectinload(User.resident_profile))
        return (await session.execute(stmt)).scalar_one_or_none()

    async def _check_lockout(self, email: str) -> None:
        cache = get_cache()
        attempts = await cache.get(f"login-attempts:{email}")
        if attempts is not None and int(attempts) >= _LOCK_THRESHOLD:
            raise RateLimitError(
                "Too many failed login attempts. Please try again in a few minutes.",
                code="account_temporarily_locked",
            )

    async def _register_failure(self, user: User | None, email: str) -> None:
        cache = get_cache()
        key = f"login-attempts:{email}"
        attempts = int(await cache.get(key) or 0) + 1
        await cache.set(key, attempts, ttl=_LOGIN_WINDOW_SECONDS)
        if user is not None:
            user.failed_login_attempts = attempts

    async def _clear_failures(self, user: User, email: str) -> None:
        await get_cache().delete(f"login-attempts:{email}")
        user.failed_login_attempts = 0

    async def authenticate(self, session: AsyncSession, email: str, password: str) -> User:
        """Validate credentials, applying lockout protection."""
        normalized = email.strip().lower()
        await self._check_lockout(normalized)
        user = await self.get_user_by_email(session, normalized)
        if user is None or not verify_password(password, user.hashed_password):
            await self._register_failure(user, normalized)
            await session.commit()
            raise AuthenticationError("Invalid email or password", code="invalid_credentials")
        if not user.is_active:
            raise AuthenticationError("This account is disabled", code="account_disabled")
        await self._clear_failures(user, normalized)
        user.last_login_at = datetime.now(UTC)
        if needs_rehash(user.hashed_password):
            user.hashed_password = hash_password(password)
        await session.commit()
        return user

    @staticmethod
    def issue_tokens(user: User) -> tuple[str, str, int]:
        """Create an access/refresh token pair for a user."""
        access_token, _ = create_access_token(user.id, str(user.role), user.compound_id)
        refresh_token, _ = create_refresh_token(user.id, str(user.role), user.compound_id)
        expires_in = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
        return access_token, refresh_token, expires_in

    async def refresh(self, session: AsyncSession, refresh_token: str) -> tuple[User, str, str, int]:
        """Rotate a refresh token, returning the user and fresh tokens."""
        payload = decode_token(refresh_token, expected_type="refresh")
        user = await self.get_user_by_id(session, payload.user_id)
        if user is None or not user.is_active:
            raise AuthenticationError("Account is no longer active", code="account_disabled")
        access_token, new_refresh, expires_in = self.issue_tokens(user)
        return user, access_token, new_refresh, expires_in

    async def change_password(
        self, session: AsyncSession, user: User, current_password: str, new_password: str
    ) -> None:
        """Change a user's password after verifying the current one."""
        if not verify_password(current_password, user.hashed_password):
            raise BadRequestError("Current password is incorrect", code="invalid_password")
        if current_password == new_password:
            raise BadRequestError("New password must differ from the current password")
        if len(new_password) < settings.PASSWORD_MIN_LENGTH:
            raise BadRequestError(
                f"Password must be at least {settings.PASSWORD_MIN_LENGTH} characters"
            )
        user.hashed_password = hash_password(new_password)
        await session.commit()

    async def resolve_token(self, session: AsyncSession, token: str) -> tuple[User, TokenPayload]:
        """Decode an access token and load the matching active user."""
        payload = decode_token(token, expected_type="access")
        user = await self.get_user_by_id(session, payload.user_id)
        if user is None:
            raise AuthenticationError("Account not found", code="invalid_token")
        if not user.is_active:
            raise AuthenticationError("This account is disabled", code="account_disabled")
        return user, payload


auth_service = AuthService()
