"""Password hashing, JWT issuing/verification and token models."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import settings
from app.core.exceptions import AuthenticationError

TokenType = Literal["access", "refresh"]

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """Hash a plaintext password using Argon2id."""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a plaintext password against an Argon2 hash."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """Return ``True`` when the stored hash uses outdated parameters."""
    try:
        return _hasher.check_needs_rehash(password_hash)
    except (InvalidHashError, ValueError):
        return True


@dataclass(frozen=True, slots=True)
class TokenPayload:
    """Decoded JWT claims."""

    user_id: uuid.UUID
    role: str
    token_type: TokenType
    jti: str
    expires_at: datetime
    compound_id: uuid.UUID | None = None


def _create_token(
    *,
    subject: uuid.UUID,
    role: str,
    token_type: TokenType,
    expires_delta: timedelta,
    compound_id: uuid.UUID | None,
) -> tuple[str, datetime]:
    now = datetime.now(UTC)
    expires_at = now + expires_delta
    claims: dict[str, Any] = {
        "sub": str(subject),
        "role": role,
        "type": token_type,
        "jti": uuid.uuid4().hex,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    if compound_id is not None:
        claims["compound_id"] = str(compound_id)
    token = jwt.encode(claims, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, expires_at


def create_access_token(
    subject: uuid.UUID, role: str, compound_id: uuid.UUID | None = None
) -> tuple[str, datetime]:
    """Create a short lived access token."""
    return _create_token(
        subject=subject,
        role=role,
        token_type="access",
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        compound_id=compound_id,
    )


def create_refresh_token(
    subject: uuid.UUID, role: str, compound_id: uuid.UUID | None = None
) -> tuple[str, datetime]:
    """Create a long lived refresh token."""
    return _create_token(
        subject=subject,
        role=role,
        token_type="refresh",
        expires_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        compound_id=compound_id,
    )


def decode_token(token: str, *, expected_type: TokenType | None = None) -> TokenPayload:
    """Decode and validate a JWT, raising :class:`AuthenticationError`."""
    try:
        claims = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["exp", "sub", "type"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Token has expired", code="token_expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("Invalid authentication token", code="invalid_token") from exc

    token_type = str(claims.get("type", ""))
    if token_type not in {"access", "refresh"}:
        raise AuthenticationError("Invalid token type", code="invalid_token")
    if expected_type is not None and token_type != expected_type:
        raise AuthenticationError(
            f"Expected a {expected_type} token", code="invalid_token_type"
        )

    compound_raw = claims.get("compound_id")
    try:
        payload = TokenPayload(
            user_id=uuid.UUID(str(claims["sub"])),
            role=str(claims.get("role", "")),
            token_type=token_type,  # type: ignore[arg-type]
            jti=str(claims.get("jti", "")),
            expires_at=datetime.fromtimestamp(int(claims["exp"]), tz=UTC),
            compound_id=uuid.UUID(compound_raw) if compound_raw else None,
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise AuthenticationError("Malformed token claims", code="invalid_token") from exc
    return payload
