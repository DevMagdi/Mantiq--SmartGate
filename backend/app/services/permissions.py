"""Role-based access control and tenant scoping helpers."""

from __future__ import annotations

import uuid

from app.core.exceptions import PermissionDeniedError
from app.models.enums import UserRole
from app.models.people import Resident
from app.models.user import User

COMPOUND_MANAGERS = (UserRole.ADMIN, UserRole.SECURITY_OFFICER)


def is_admin(user: User) -> bool:
    """Return ``True`` for platform administrators."""
    return user.role == UserRole.ADMIN


def is_manager(user: User) -> bool:
    """Return ``True`` for admins and security officers."""
    return user.role in COMPOUND_MANAGERS


def require_roles(user: User, *roles: UserRole) -> None:
    """Raise 403 unless the user holds one of ``roles``."""
    if user.role not in roles:
        raise PermissionDeniedError("You do not have permission to perform this action")


def require_manager(user: User) -> None:
    """Raise 403 unless the user can manage compound resources."""
    if not is_manager(user):
        raise PermissionDeniedError("Compound management requires an officer or admin role")


def require_admin(user: User) -> None:
    """Raise 403 unless the user is an administrator."""
    if not is_admin(user):
        raise PermissionDeniedError("Administrator privileges are required")


def compound_scope(user: User, requested: uuid.UUID | None) -> uuid.UUID | None:
    """Resolve the compound filter a user may query.

    Admins may query across compounds (``None`` means all). Everyone else is
    pinned to their own compound and cannot request another one.
    """
    if is_admin(user):
        return requested
    if user.compound_id is None:
        raise PermissionDeniedError("Your account is not attached to a compound")
    if requested is not None and requested != user.compound_id:
        raise PermissionDeniedError("You cannot access another compound")
    return user.compound_id


def enforce_compound(user: User, compound_id: uuid.UUID) -> None:
    """Raise 403 when a non-admin targets a different compound."""
    if is_admin(user):
        return
    if user.compound_id != compound_id:
        raise PermissionDeniedError("You cannot access another compound")


def resident_profile(user: User) -> Resident:
    """Return the resident profile of the logged-in resident or raise 403."""
    profile = user.resident_profile
    if profile is None:
        raise PermissionDeniedError("No resident profile is linked to this account")
    return profile


def can_manage_residents(user: User) -> bool:
    return is_manager(user)
