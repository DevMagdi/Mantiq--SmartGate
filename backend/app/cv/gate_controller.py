"""Access decision engine and physical gate controller.

The decision engine is deliberately deterministic and database-driven: every
allow/deny outcome can be traced to a rule with a stable ``reason_code`` that is
stored on the access log and shown in the dashboard.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import publish_event
from app.core.logging import get_logger
from app.models.base import as_utc
from app.models.compound import Compound, Gate
from app.models.enums import (
    AccessDecision,
    AccessDirection,
    AccessMethod,
    BlacklistEntryType,
    GateDirection,
    PermitStatus,
    ResidentStatus,
    VehicleStatus,
    VisitorStatus,
)
from app.models.people import Permit, Resident, Visitor
from app.models.security import BlacklistEntry
from app.models.vehicle import Vehicle
from app.core.metrics import record_barrier_command
from app.cv.actuators import (
    BARRIER_ACTIONS,
    ActuatorRegistry,
    ActuatorResult,
    SimulatedActuator,
    WebhookActuator,
    actuator_registry,
    command_journal,
)
from app.cv.utils import normalize_plate, plate_variants
from app.services.compound_policy import AccessPolicy, CompoundPolicy

logger = get_logger(__name__)


# Stable reason codes (also used by the dashboard decision explainer).
class ReasonCode:
    """Reason code constants for access decisions."""

    BLACKLIST_PLATE = "blacklist_plate"
    BLACKLIST_FACE = "blacklist_face"
    BLACKLIST_PERSON = "blacklist_person"
    REGISTERED_VEHICLE = "registered_vehicle"
    REGISTERED_VEHICLE_WITH_FACE = "registered_vehicle_with_face"
    FACE_MATCHED_RESIDENT = "face_matched_resident"
    VEHICLE_SUSPENDED = "vehicle_suspended"
    VEHICLE_INACTIVE = "vehicle_inactive"
    RESIDENT_INACTIVE = "resident_inactive"
    VISITOR_PERMIT = "visitor_permit"
    PERMIT_EXPIRED = "permit_expired"
    PERMIT_REVOKED = "permit_revoked"
    PERMIT_NOT_STARTED = "permit_not_started"
    PERMIT_EXHAUSTED = "permit_exhausted"
    PERMIT_EXISTS_NO_VEHICLE = "permit_registered_without_plate"
    VEHICLE_OWNER_MISMATCH = "vehicle_owner_mismatch"
    KNOWN_FACE_UNKNOWN_VEHICLE = "known_face_unknown_vehicle"
    UNKNOWN_PLATE = "unknown_plate"
    UNKNOWN_VISITOR_NO_PERMIT = "visitor_vehicle_without_permit"
    NO_SIGNAL = "no_detection"
    VISITOR_STATUS_INVALID = "visitor_status_invalid"
    VISITOR_EXIT = "visitor_exit"
    REGISTERED_EXIT = "registered_exit"
    MANUAL_OVERRIDE = "manual_override"
    FACE_REQUIRED_MISSING = "face_required_missing"
    BLACKLIST_EXIT_ALLOWED = "blacklist_exit_allowed"


REASON_MESSAGES: dict[str, str] = {
    ReasonCode.BLACKLIST_PLATE: "Vehicle plate is on the blacklist",
    ReasonCode.BLACKLIST_FACE: "Person is on the face blacklist",
    ReasonCode.BLACKLIST_PERSON: "Person is on the blacklist",
    ReasonCode.REGISTERED_VEHICLE: "Registered resident vehicle",
    ReasonCode.REGISTERED_VEHICLE_WITH_FACE: "Registered vehicle with matched resident face",
    ReasonCode.FACE_MATCHED_RESIDENT: "Resident identified by face recognition",
    ReasonCode.VEHICLE_SUSPENDED: "Vehicle access is suspended",
    ReasonCode.VEHICLE_INACTIVE: "Vehicle is inactive",
    ReasonCode.RESIDENT_INACTIVE: "Resident access is inactive",
    ReasonCode.VISITOR_PERMIT: "Valid visitor permit",
    ReasonCode.PERMIT_EXPIRED: "Visitor permit has expired",
    ReasonCode.PERMIT_REVOKED: "Visitor permit was revoked",
    ReasonCode.PERMIT_NOT_STARTED: "Visitor permit is not valid yet",
    ReasonCode.PERMIT_EXHAUSTED: "Visitor permit entry limit reached",
    ReasonCode.PERMIT_EXISTS_NO_VEHICLE: "A permit exists but no plate is registered for it",
    ReasonCode.VEHICLE_OWNER_MISMATCH: "Vehicle belongs to another resident than the recognised face",
    ReasonCode.KNOWN_FACE_UNKNOWN_VEHICLE: "Recognised resident in an unregistered vehicle",
    ReasonCode.UNKNOWN_PLATE: "Plate is not registered in this compound",
    ReasonCode.UNKNOWN_VISITOR_NO_PERMIT: "Visitor vehicle has no valid permit",
    ReasonCode.NO_SIGNAL: "No plate or face could be detected",
    ReasonCode.VISITOR_STATUS_INVALID: "Visitor record does not allow entry",
    ReasonCode.VISITOR_EXIT: "Visitor checking out of the compound",
    ReasonCode.REGISTERED_EXIT: "Vehicle exiting the compound",
    ReasonCode.MANUAL_OVERRIDE: "Decision overridden by a security officer",
    ReasonCode.FACE_REQUIRED_MISSING: "Compound policy requires a recognised driver face",
    ReasonCode.BLACKLIST_EXIT_ALLOWED: "Blacklisted entity allowed to leave the compound",
}


def describe_reason(reason_code: str) -> str:
    """Human sentence for a reason code (used by the dashboard explainer)."""
    return REASON_MESSAGES.get(reason_code, reason_code.replace("_", " ").title())


@dataclass(slots=True)
class DecisionContext:
    """All signals available for a single access decision."""

    gate: Gate
    plate_text: str | None = None
    plate_confidence: float | None = None
    face_resident_id: uuid.UUID | None = None
    face_similarity: float | None = None
    face_embedding_id: uuid.UUID | None = None
    blacklisted_embedding_ids: frozenset[uuid.UUID] = frozenset()
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True)
class DecisionResult:
    """The outcome of evaluating all access rules."""

    decision: AccessDecision
    reason_code: str
    reason: str
    method: AccessMethod
    direction: AccessDirection
    requires_review: bool
    open_barrier: bool
    vehicle: Vehicle | None = None
    resident: Resident | None = None
    visitor: Visitor | None = None
    permit: Permit | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "reason_code": self.reason_code,
            "reason": self.reason,
            "method": self.method.value,
            "direction": self.direction.value,
            "requires_review": self.requires_review,
            "open_barrier": self.open_barrier,
            "vehicle_id": str(self.vehicle.id) if self.vehicle else None,
            "resident_id": str(self.resident.id) if self.resident else None,
            "visitor_id": str(self.visitor.id) if self.visitor else None,
            "permit_id": str(self.permit.id) if self.permit else None,
            "details": self.details,
        }


def resolve_direction(gate: Gate, vehicle: Vehicle | None) -> AccessDirection:
    """Infer traffic direction from the gate configuration and vehicle presence."""
    if gate.direction == GateDirection.ENTRY:
        return AccessDirection.ENTRY
    if gate.direction == GateDirection.EXIT:
        return AccessDirection.EXIT
    if vehicle is not None and vehicle.is_inside:
        return AccessDirection.EXIT
    return AccessDirection.ENTRY


class AccessDecisionEngine:
    """Evaluates the access rules for a detection."""

    async def decide(
        self, session: AsyncSession, context: DecisionContext
    ) -> DecisionResult:
        gate = context.gate
        now = as_utc(context.occurred_at)
        policy = await self.policy(session, gate.compound_id)
        access: AccessPolicy = policy.access
        normalized_plate = normalize_plate(context.plate_text)
        lookup_keys = plate_variants(context.plate_text)

        vehicle = await self._find_vehicle(session, gate.compound_id, lookup_keys)
        face_resident = await self._find_resident(
            session, context.face_resident_id, gate.compound_id
        )
        permits = await self._find_permits(
            session, gate.compound_id, lookup_keys, vehicle
        )
        permit, permit_reason = self._select_permit(permits, now)
        direction = resolve_direction(gate, vehicle)

        def result(
            decision: AccessDecision,
            reason_code: str,
            method: AccessMethod,
            *,
            resident: Resident | None = None,
            chosen_permit: Permit | None = None,
            open_barrier: bool | None = None,
            details: dict[str, Any] | None = None,
        ) -> DecisionResult:
            allow_auto_open = access.auto_open_barrier
            return DecisionResult(
                decision=decision,
                reason_code=reason_code,
                reason=describe_reason(reason_code),
                method=method,
                direction=direction,
                requires_review=decision == AccessDecision.REVIEW,
                open_barrier=(decision == AccessDecision.ALLOW and allow_auto_open)
                if open_barrier is None
                else open_barrier,
                vehicle=vehicle,
                resident=resident or face_resident,
                visitor=chosen_permit.visitor if chosen_permit else None,
                permit=chosen_permit,
                details=details or {},
            )

        # ------------------------------------------------------------ 1. blacklist
        blacklist_hit = await self._blacklist_hit(
            session,
            compound_id=gate.compound_id,
            normalized_plate=normalized_plate,
            lookup_keys=lookup_keys,
            resident_id=context.face_resident_id,
            visitor_id=permit.visitor_id if permit else None,
            embedding_ids=context.blacklisted_embedding_ids,
            face_embedding_id=context.face_embedding_id,
            at=now,
        )
        if blacklist_hit is not None:
            reason_code = {
                BlacklistEntryType.PLATE: ReasonCode.BLACKLIST_PLATE,
                BlacklistEntryType.FACE: ReasonCode.BLACKLIST_FACE,
                BlacklistEntryType.PERSON: ReasonCode.BLACKLIST_PERSON,
            }[blacklist_hit.entry_type]
            if direction == AccessDirection.EXIT and access.allow_blacklist_exit:
                return result(
                    AccessDecision.ALLOW,
                    ReasonCode.BLACKLIST_EXIT_ALLOWED,
                    AccessMethod.COMBINED if context.face_resident_id else AccessMethod.PLATE,
                    details={
                        "blacklist_entry_id": str(blacklist_hit.id),
                        "blacklist_reason": blacklist_hit.reason.value
                        if hasattr(blacklist_hit.reason, "value")
                        else str(blacklist_hit.reason),
                    },
                )
            return result(
                AccessDecision.DENY,
                reason_code,
                AccessMethod.COMBINED if context.face_resident_id else AccessMethod.PLATE,
                open_barrier=False,
                details={"blacklist_entry_id": str(blacklist_hit.id)},
            )

        # ------------------------------------------------------- 2. exit handling
        # Vehicles (and checked-in visitors) must always be able to leave, even
        # when their permit window closed while they were inside.
        if direction == AccessDirection.EXIT:
            if vehicle is not None and vehicle.is_inside:
                method = AccessMethod.COMBINED if face_resident is not None else AccessMethod.PLATE
                return result(
                    AccessDecision.ALLOW,
                    ReasonCode.REGISTERED_EXIT,
                    method,
                    resident=vehicle.resident,
                )
            if (
                permit is not None
                and permit.visitor is not None
                and permit.visitor.status == VisitorStatus.CHECKED_IN
            ):
                return result(
                    AccessDecision.ALLOW,
                    ReasonCode.VISITOR_EXIT,
                    AccessMethod.PERMIT,
                    chosen_permit=permit,
                )

        # ------------------------------------------------------ 3. registered vehicle
        if vehicle is not None:
            owner = vehicle.resident
            if vehicle.status == VehicleStatus.SUSPENDED:
                return result(AccessDecision.DENY, ReasonCode.VEHICLE_SUSPENDED, AccessMethod.PLATE)
            if vehicle.status == VehicleStatus.INACTIVE:
                return result(AccessDecision.DENY, ReasonCode.VEHICLE_INACTIVE, AccessMethod.PLATE)
            if owner is not None:
                if owner.status != ResidentStatus.ACTIVE:
                    return result(
                        AccessDecision.DENY,
                        ReasonCode.RESIDENT_INACTIVE,
                        AccessMethod.PLATE,
                        resident=owner,
                        details={"resident_status": owner.status.value},
                    )
                if face_resident is not None and face_resident.id != owner.id:
                    return result(
                        AccessDecision.REVIEW,
                        ReasonCode.VEHICLE_OWNER_MISMATCH,
                        AccessMethod.COMBINED,
                        resident=owner,
                        open_barrier=False,
                        details={
                            "vehicle_owner_id": str(owner.id),
                            "recognised_resident_id": str(face_resident.id),
                        },
                    )
                if access.require_face_for_vehicle and face_resident is None:
                    return result(
                        AccessDecision.REVIEW,
                        ReasonCode.FACE_REQUIRED_MISSING,
                        AccessMethod.PLATE,
                        resident=owner,
                        open_barrier=False,
                        details={"policy": "require_face_for_vehicle"},
                    )
                method = (
                    AccessMethod.COMBINED
                    if face_resident is not None
                    else AccessMethod.PLATE
                )
                reason_code = (
                    ReasonCode.REGISTERED_VEHICLE_WITH_FACE
                    if face_resident is not None
                    else ReasonCode.REGISTERED_VEHICLE
                )
                return result(AccessDecision.ALLOW, reason_code, method, resident=owner)

        # ------------------------------------------------------------- 4. permits
        if permit is not None and permit_reason is None:
            visitor = permit.visitor
            if visitor is not None and visitor.status in {
                VisitorStatus.REJECTED,
                VisitorStatus.CANCELLED,
            }:
                return result(
                    AccessDecision.DENY,
                    ReasonCode.VISITOR_STATUS_INVALID,
                    AccessMethod.PERMIT,
                    chosen_permit=permit,
                    open_barrier=False,
                )
            return result(
                AccessDecision.ALLOW,
                ReasonCode.VISITOR_PERMIT,
                AccessMethod.PERMIT,
                chosen_permit=permit,
                details={
                    "permit_code": permit.permit_code,
                    "valid_until": as_utc(permit.end_at).isoformat(),
                },
            )
        if permit is not None and permit_reason is not None:
            return result(
                AccessDecision.DENY,
                permit_reason,
                AccessMethod.PERMIT,
                chosen_permit=permit,
                open_barrier=False,
            )

        # -------------------------------------------------------- 5. face recognition
        allow_face_entry = access.allow_face_only_entry
        if face_resident is not None:
            if face_resident.status != ResidentStatus.ACTIVE:
                return result(
                    AccessDecision.DENY,
                    ReasonCode.RESIDENT_INACTIVE,
                    AccessMethod.FACE,
                    resident=face_resident,
                    open_barrier=False,
                )
            if normalized_plate and vehicle is None:
                return result(
                    AccessDecision.REVIEW,
                    ReasonCode.KNOWN_FACE_UNKNOWN_VEHICLE,
                    AccessMethod.COMBINED,
                    resident=face_resident,
                    open_barrier=False,
                    details={"plate": context.plate_text},
                )
            if allow_face_entry:
                return result(
                    AccessDecision.ALLOW,
                    ReasonCode.FACE_MATCHED_RESIDENT,
                    AccessMethod.FACE,
                    resident=face_resident,
                    details={"similarity": context.face_similarity},
                )

        # ------------------------------------------------------------- 6. unknown
        # The compound decides whether an unregistered vehicle is silently
        # logged ("unknown") or queued for a human ("review") / refused.
        fallback = access.unknown_vehicle_decision
        if normalized_plate:
            if vehicle is not None:
                # Visitor vehicle registered without a permit.
                return result(
                    fallback,
                    ReasonCode.UNKNOWN_VISITOR_NO_PERMIT,
                    AccessMethod.PLATE,
                    open_barrier=False,
                )
            return result(
                fallback,
                ReasonCode.UNKNOWN_PLATE,
                AccessMethod.PLATE,
                open_barrier=False,
                details={"plate": context.plate_text, "policy": "unknown_vehicle_decision"},
            )
        return result(
            fallback,
            ReasonCode.NO_SIGNAL,
            AccessMethod.PLATE,
            open_barrier=False,
        )

    # ------------------------------------------------------------------ queries
    async def policy(self, session: AsyncSession, compound_id: uuid.UUID) -> CompoundPolicy:
        """Load the validated operational policy for a compound."""
        compound = await session.get(Compound, compound_id)
        return CompoundPolicy.from_settings(compound.settings if compound else None)

    async def _find_vehicle(
        self, session: AsyncSession, compound_id: uuid.UUID, lookup_keys: set[str]
    ) -> Vehicle | None:
        if not lookup_keys:
            return None
        stmt = (
            select(Vehicle)
            .where(
                Vehicle.compound_id == compound_id,
                Vehicle.plate_normalized.in_(lookup_keys),
            )
            .limit(1)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def _find_resident(
        self, session: AsyncSession, resident_id: uuid.UUID | None, compound_id: uuid.UUID
    ) -> Resident | None:
        if resident_id is None:
            return None
        resident = await session.get(Resident, resident_id)
        if resident is None or resident.compound_id != compound_id:
            logger.warning("Face matched a resident outside the compound: %s", resident_id)
            return None
        return resident

    async def _find_permits(
        self,
        session: AsyncSession,
        compound_id: uuid.UUID,
        lookup_keys: set[str],
        vehicle: Vehicle | None,
    ) -> list[Permit]:
        if not lookup_keys:
            return []
        conditions = []
        if vehicle is not None:
            conditions.append(Permit.vehicle_id == vehicle.id)
        conditions.append(
            Permit.vehicle_id.in_(
                select(Vehicle.id).where(
                    Vehicle.compound_id == compound_id,
                    Vehicle.plate_normalized.in_(lookup_keys),
                )
            )
        )
        stmt = (
            select(Permit)
            .where(Permit.compound_id == compound_id, or_(*conditions))
            .order_by(Permit.end_at.desc())
            .limit(10)
        )
        return list((await session.execute(stmt)).scalars().unique().all())

    def _select_permit(
        self, permits: list[Permit], now: datetime
    ) -> tuple[Permit | None, str | None]:
        """Return the best permit and, when none is valid, why."""
        if not permits:
            return None, None
        valid = [permit for permit in permits if permit.is_currently_valid(now)]
        if valid:
            valid.sort(key=lambda permit: as_utc(permit.end_at), reverse=True)
            return valid[0], None
        # Report the most actionable failure from the newest permit.
        permit = permits[0]
        if permit.status == PermitStatus.REVOKED:
            return permit, ReasonCode.PERMIT_REVOKED
        if permit.status == PermitStatus.PENDING or as_utc(permit.start_at) > now:
            return permit, ReasonCode.PERMIT_NOT_STARTED
        if as_utc(permit.end_at) < now or permit.status == PermitStatus.EXPIRED:
            return permit, ReasonCode.PERMIT_EXPIRED
        if permit.entries_used >= permit.max_entries:
            return permit, ReasonCode.PERMIT_EXHAUSTED
        return permit, ReasonCode.PERMIT_EXPIRED

    async def _blacklist_hit(
        self,
        session: AsyncSession,
        *,
        compound_id: uuid.UUID,
        normalized_plate: str,
        lookup_keys: set[str],
        resident_id: uuid.UUID | None,
        visitor_id: uuid.UUID | None,
        embedding_ids: frozenset[uuid.UUID],
        face_embedding_id: uuid.UUID | None,
        at: datetime,
    ) -> BlacklistEntry | None:
        conditions = []
        if lookup_keys:
            conditions.append(
                and_(
                    BlacklistEntry.entry_type == BlacklistEntryType.PLATE,
                    BlacklistEntry.plate_normalized.in_(lookup_keys),
                )
            )
        if resident_id is not None:
            conditions.append(
                and_(
                    BlacklistEntry.entry_type == BlacklistEntryType.PERSON,
                    BlacklistEntry.resident_id == resident_id,
                )
            )
        if visitor_id is not None:
            conditions.append(BlacklistEntry.visitor_id == visitor_id)
        candidate_embeddings = set(embedding_ids)
        if face_embedding_id is not None:
            candidate_embeddings.add(face_embedding_id)
        if candidate_embeddings:
            conditions.append(
                and_(
                    BlacklistEntry.entry_type == BlacklistEntryType.FACE,
                    BlacklistEntry.face_embedding_id.in_(candidate_embeddings),
                )
            )
        if not conditions:
            return None
        stmt = (
            select(BlacklistEntry)
            .where(
                BlacklistEntry.compound_id == compound_id,
                BlacklistEntry.is_active.is_(True),
                or_(BlacklistEntry.expires_at.is_(None), BlacklistEntry.expires_at > at),
                or_(*conditions),
            )
            .order_by(BlacklistEntry.created_at.desc())
            .limit(1)
        )
        return (await session.execute(stmt)).scalar_one_or_none()


# Backwards-compatible aliases: the actuators now live in ``app.cv.actuators``.
SimulatedGateActuator = SimulatedActuator
WebhookGateActuator = WebhookActuator


@dataclass(slots=True)
class GateCommand:
    """Result of one barrier command (also journaled and broadcast)."""

    gate_id: uuid.UUID
    action: str
    accepted: bool
    detail: str
    driver: str = "simulator"
    latency_ms: int = 0
    command_id: str | None = None


class GateController:
    """Executes barrier commands through the compound's configured actuator.

    Commands are signed/sent by the driver selected in the compound barrier
    policy (simulator, webhook, mqtt or gpio), journaled for the dashboard and
    broadcast on the WebSocket bus so every console sees the same event.
    """

    def __init__(self, registry: ActuatorRegistry | None = None) -> None:
        self.registry = registry or actuator_registry
        self.journal = command_journal

    async def execute(
        self,
        gate: Gate,
        compound: Compound | None,
        action: str,
        reason: str,
        *,
        actor: str = "system",
    ) -> GateCommand:
        if action not in BARRIER_ACTIONS:
            self.journal.record(
                gate_code=gate.code,
                action=action,
                result=ActuatorResult(
                    accepted=False,
                    driver="none",
                    detail=f"Unsupported action: {action}",
                    error="unsupported_action",
                ),
                actor=actor,
                reason=reason,
                gate_id=gate.id,
                compound_id=gate.compound_id,
            )
            return GateCommand(gate.id, action, False, f"Unsupported action: {action}")

        policy = CompoundPolicy.from_settings(compound.settings if compound else None)
        try:
            actuator = await self.registry.for_policy(gate.compound_id, policy.barrier)
            result = await actuator.send(action, gate.code, reason)
        except Exception as exc:  # pragma: no cover - defensive: never block the log
            logger.exception("Barrier actuator crashed for gate %s", gate.code)
            result = ActuatorResult(
                accepted=False,
                driver=policy.barrier.driver,
                detail=f"Actuator error: {type(exc).__name__}: {exc}",
                error=str(exc),
            )

        record_barrier_command(result.driver, action, result.accepted)
        record = self.journal.record(
            gate_code=gate.code,
            action=action,
            result=result,
            actor=actor,
            reason=reason,
            gate_id=gate.id,
            compound_id=gate.compound_id,
        )
        await publish_event(
            "gate.command",
            {
                "gate_id": str(gate.id),
                "gate_code": gate.code,
                "compound_id": str(gate.compound_id),
                "action": action,
                "accepted": result.accepted,
                "reason": reason,
                "actor": actor,
                "driver": result.driver,
                "latency_ms": result.latency_ms,
                "attempts": result.attempts,
                "detail": result.detail,
                "command_id": record.id,
            },
        )
        log = logger.info if result.accepted else logger.warning
        log(
            "Barrier command gate=%s action=%s driver=%s accepted=%s latency=%dms actor=%s detail=%s",
            gate.code,
            action,
            result.driver,
            result.accepted,
            result.latency_ms,
            actor,
            result.detail,
        )
        return GateCommand(
            gate.id,
            action,
            result.accepted,
            result.detail,
            driver=result.driver,
            latency_ms=result.latency_ms,
            command_id=record.id,
        )

    def status(self, compound_id: uuid.UUID) -> dict[str, Any]:
        """Driver health plus recent commands for one compound."""
        return {
            "actuator": self.registry.status(compound_id),
            "journal": self.journal.summary(),
            "recent_commands": [
                item.as_dict() for item in self.journal.recent(20, compound_id=str(compound_id))
            ],
        }


_gate_controller: GateController | None = None


def get_gate_controller() -> GateController:
    """Return the process-wide gate controller."""
    global _gate_controller
    if _gate_controller is None:
        _gate_controller = GateController()
    return _gate_controller


__all__ = [
    "AccessDecisionEngine",
    "DecisionContext",
    "DecisionResult",
    "GateCommand",
    "GateController",
    "ReasonCode",
    "REASON_MESSAGES",
    "SimulatedGateActuator",
    "WebhookGateActuator",
    "actuator_registry",
    "command_journal",
    "get_gate_controller",
    "resolve_direction",
]
