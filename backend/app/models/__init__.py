"""ORM model registry.

Importing this package registers every model on the shared metadata, which is
required by Alembic autogeneration and by the test fixtures that call
``Base.metadata.create_all``.
"""

from app.models.access import AccessLog, DetectionEvent
from app.models.base import Base, as_utc, utcnow
from app.models.compound import Camera, Compound, Gate, Unit
from app.models.enums import (
    AccessDecision,
    AccessDirection,
    AccessMethod,
    BlacklistEntryType,
    BlacklistReason,
    CameraSourceType,
    CameraStatus,
    DetectionType,
    EmbeddingSource,
    GateDirection,
    GateStatus,
    PermitStatus,
    PermitType,
    ResidentRelationship,
    ResidentStatus,
    UnitStatus,
    UnitType,
    UserRole,
    VehicleStatus,
    VehicleType,
    VisitorStatus,
)
from app.models.people import Permit, Resident, Visitor
from app.models.security import BlacklistEntry, FaceEmbedding
from app.models.user import User
from app.models.vehicle import Vehicle

__all__ = [
    "AccessDecision",
    "AccessDirection",
    "AccessLog",
    "AccessMethod",
    "Base",
    "BlacklistEntry",
    "BlacklistEntryType",
    "BlacklistReason",
    "Camera",
    "CameraSourceType",
    "CameraStatus",
    "Compound",
    "DetectionEvent",
    "DetectionType",
    "EmbeddingSource",
    "FaceEmbedding",
    "Gate",
    "GateDirection",
    "GateStatus",
    "Permit",
    "PermitStatus",
    "PermitType",
    "Resident",
    "ResidentRelationship",
    "ResidentStatus",
    "Unit",
    "UnitStatus",
    "UnitType",
    "User",
    "UserRole",
    "Vehicle",
    "VehicleStatus",
    "VehicleType",
    "Visitor",
    "VisitorStatus",
    "as_utc",
    "utcnow",
]
