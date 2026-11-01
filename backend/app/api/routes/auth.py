"""Authentication endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    RefreshRequest,
    TokenPair,
    UserRead,
)
from app.schemas.common import Message
from app.services.auth_service import auth_service

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _token_pair(user, access_token: str, refresh_token: str, expires_in: int) -> TokenPair:
    return TokenPair(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
        user=UserRead.from_user(user),
    )


@router.post(
    "/login",
    response_model=TokenPair,
    summary="Sign in with email and password",
    responses={401: {"description": "Invalid credentials"}, 429: {"description": "Locked out"}},
)
async def login(payload: LoginRequest, session: SessionDep) -> TokenPair:
    """Authenticate a user and return a JWT access/refresh pair."""
    user = await auth_service.authenticate(session, str(payload.email), payload.password)
    access_token, refresh_token, expires_in = auth_service.issue_tokens(user)
    return _token_pair(user, access_token, refresh_token, expires_in)


@router.post(
    "/token",
    response_model=TokenPair,
    summary="OAuth2 password flow (Swagger UI)",
    include_in_schema=True,
)
async def login_form(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: SessionDep,
) -> TokenPair:
    """OAuth2 compatible endpoint used by the interactive API docs."""
    user = await auth_service.authenticate(session, form.username, form.password)
    access_token, refresh_token, expires_in = auth_service.issue_tokens(user)
    return _token_pair(user, access_token, refresh_token, expires_in)


@router.post(
    "/refresh",
    response_model=TokenPair,
    summary="Rotate an expired access token",
    responses={401: {"description": "Invalid refresh token"}},
)
async def refresh(payload: RefreshRequest, session: SessionDep) -> TokenPair:
    """Exchange a refresh token for a fresh token pair."""
    user, access_token, refresh_token, expires_in = await auth_service.refresh(
        session, payload.refresh_token
    )
    return _token_pair(user, access_token, refresh_token, expires_in)


@router.get("/me", response_model=UserRead, summary="Current authenticated user")
async def me(user: CurrentUser) -> UserRead:
    """Return the profile of the authenticated user."""
    return UserRead.from_user(user)


@router.post(
    "/change-password",
    response_model=Message,
    status_code=status.HTTP_200_OK,
    summary="Change your password",
)
async def change_password(
    payload: ChangePasswordRequest, session: SessionDep, user: CurrentUser
) -> Message:
    """Change the current user's password after verifying the old one."""
    await auth_service.change_password(
        session, user, payload.current_password, payload.new_password
    )
    return Message(message="Password updated successfully")


@router.post("/logout", response_model=Message, summary="Client-side logout")
async def logout(user: CurrentUser) -> Message:
    """Stateless logout: discard the tokens on the client.

    Access tokens are short lived (``ACCESS_TOKEN_EXPIRE_MINUTES``) and refresh
    tokens are rotated on every use, so no server-side revocation list is
    required for this deployment model.
    """
    return Message(
        message="Signed out",
        detail=f"Discard the stored tokens for {user.email} (lifetime {settings.ACCESS_TOKEN_EXPIRE_MINUTES} minutes).",
    )
