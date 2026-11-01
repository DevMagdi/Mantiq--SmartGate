"""Domain enumerations shared by models, schemas and services."""

from __future__ import annotations

from enum import StrEnum


class UserRole(StrEnum):
    """Roles supported by the role-based access control system."""

    ADMIN = "admin"
    SECURITY_OFFICER = "security_officer"
    RESIDENT = "resident"


class GateDirection(StrEnum):
    """Traffic direction handled by a gate."""

    ENTRY = "entry"
    EXIT = "exit"
    BIDIRECTIONAL = "bidirectional"


class GateStatus(StrEnum):
    """Operational status of a physical gate."""

    ONLINE = "online"
    OFFLINE = "offline"
    MAINTENANCE = "maintenance"


class CameraSourceType(StrEnum):
    """Supported camera transports."""

    RTSP = "rtsp"
    USB = "usb"
    FILE = "file"
    DEMO = "demo"


class CameraStatus(StrEnum):
    """Runtime health of a camera stream."""

    ONLINE = "online"
    OFFLINE = "offline"
    ERROR = "error"
    DISABLED = "disabled"


class UnitType(StrEnum):
    """Unit categories inside a compound."""

    APARTMENT = "apartment"
    VILLA = "villa"
    TOWNHOUSE = "townhouse"
    OFFICE = "office"
    OTHER = "other"


class UnitStatus(StrEnum):
    """Occupancy status of a unit."""

    OCCUPIED = "occupied"
    VACANT = "vacant"


class ResidentRelationship(StrEnum):
    """How a resident relates to their unit."""

    OWNER = "owner"
    TENANT = "tenant"
    FAMILY = "family"


class ResidentStatus(StrEnum):
    """Lifecycle status of a resident profile."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    MOVED_OUT = "moved_out"


class VehicleType(StrEnum):
    """Supported vehicle categories."""

    CAR = "car"
    MOTORCYCLE = "motorcycle"
    VAN = "van"
    TRUCK = "truck"
    OTHER = "other"


class VehicleStatus(StrEnum):
    """Administrative status of a vehicle."""

    ACTIVE = "active"
    SUSPENDED = "suspended"
    INACTIVE = "inactive"


class VisitorStatus(StrEnum):
    """Lifecycle of a visitor record."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CHECKED_IN = "checked_in"
    CHECKED_OUT = "checked_out"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class PermitType(StrEnum):
    """Reasons a temporary gate permit can be issued."""

    VISITOR = "visitor"
    CONTRACTOR = "contractor"
    DELIVERY = "delivery"
    TEMPORARY_RESIDENT = "temporary_resident"
    EVENT = "event"


class PermitStatus(StrEnum):
    """Validity state of a permit."""

    PENDING = "pending"
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"


class AccessDecision(StrEnum):
    """Outcome produced by the access decision engine."""

    ALLOW = "allow"
    DENY = "deny"
    UNKNOWN = "unknown"
    REVIEW = "review"


class AccessMethod(StrEnum):
    """How a decision was reached."""

    PLATE = "plate"
    FACE = "face"
    COMBINED = "combined"
    PERMIT = "permit"
    MANUAL = "manual"


class DetectionType(StrEnum):
    """Kind of signal captured by a camera."""

    PLATE = "plate"
    FACE = "face"
    COMBINED = "combined"
    MANUAL = "manual"


class BlacklistEntryType(StrEnum):
    """Entity a blacklist entry applies to."""

    PLATE = "plate"
    FACE = "face"
    PERSON = "person"


class BlacklistReason(StrEnum):
    """Why an entity was blacklisted."""

    THEFT = "theft"
    SECURITY = "security"
    UNPAID_DUES = "unpaid_dues"
    TRESPASSING = "trespassing"
    COURT_ORDER = "court_order"
    OTHER = "other"


class EmbeddingSource(StrEnum):
    """Where a face embedding came from."""

    ENROLLMENT = "enrollment"
    DETECTION = "detection"


class AccessDirection(StrEnum):
    """Direction recorded on an access log (mirrors gate direction)."""

    ENTRY = "entry"
    EXIT = "exit"


ROLE_LABELS: dict[UserRole, str] = {
    UserRole.ADMIN: "Administrator",
    UserRole.SECURITY_OFFICER: "Security Officer",
    UserRole.RESIDENT: "Resident",
}
