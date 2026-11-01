"""Demo data seeding.

Creates a realistic compound (residents, vehicles, permits, blacklists, faces and
historical access logs) plus the default accounts. Safe to run repeatedly: the
seeder is idempotent and only fills what is missing.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import cv2
import numpy as np
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import hash_password
from app.cv.snapshots import SnapshotStore
from app.cv.utils import deterministic_embedding, normalize_plate
from app.models.access import AccessLog, DetectionEvent
from app.models.base import as_utc
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

logger = get_logger(__name__)

DEMO_TIMEZONE = ZoneInfo("Africa/Cairo")
DEMO_PERMIT_DAYS = 7


def _placeholder_face(name: str) -> np.ndarray:
    """Create a deterministic avatar image for seeded face embeddings."""
    image = np.full((240, 240, 3), (42, 44, 48), dtype=np.uint8)
    cv2.circle(image, (120, 100), 58, (168, 178, 190), -1)
    cv2.circle(image, (100, 90), 6, (40, 40, 44), -1)
    cv2.circle(image, (140, 90), 6, (40, 40, 44), -1)
    cv2.ellipse(image, (120, 122), (20, 9), 0, 0, 180, (90, 90, 96), 2)
    cv2.circle(image, (120, 210), 70, (52, 58, 70), -1)
    cv2.putText(
        image,
        name.upper()[:16],
        (14, 232),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (220, 225, 230),
        1,
        cv2.LINE_AA,
    )
    return image


def _permit_code(prefix: str = "PMT") -> str:
    return f"{prefix}-{datetime.now(UTC).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"


class SeedService:
    """Idempotent demo data generator."""

    def __init__(self) -> None:
        self.store = SnapshotStore()

    async def ensure_admin(self, session: AsyncSession) -> User | None:
        """Create the bootstrap administrator when no account exists."""
        existing = await session.scalar(
            select(User).where(User.email == settings.SEED_ADMIN_EMAIL.lower())
        )
        if existing is not None:
            return existing
        user_count = await session.scalar(select(func.count(User.id))) or 0
        admin = User(
            email=settings.SEED_ADMIN_EMAIL.lower(),
            hashed_password=hash_password(settings.SEED_ADMIN_PASSWORD),
            full_name=settings.SEED_ADMIN_NAME,
            role=UserRole.ADMIN,
            is_active=True,
            phone="+20 100 000 0000",
        )
        session.add(admin)
        await session.flush()
        if user_count == 0:
            logger.info("Bootstrap admin created: %s", admin.email)
        return admin

    async def seed_demo(self, session: AsyncSession, *, with_history: bool = True) -> dict[str, int]:
        """Create the demo compound unless it already exists."""
        admin = await self.ensure_admin(session)
        compound = await session.scalar(
            select(Compound).where(Compound.code == settings.DEMO_COMPOUND_CODE.upper())
        )
        if compound is not None:
            await session.commit()
            logger.info("Demo compound already exists, skipping demo seeding")
            return {"created": 0, "skipped": 1}

        now_local = datetime.now(DEMO_TIMEZONE)
        compound = Compound(
            name=settings.DEMO_COMPOUND_NAME,
            code=settings.DEMO_COMPOUND_CODE.upper(),
            address="Palm Hills, 6th of October",
            city="Cairo",
            country="EG",
            timezone="Africa/Cairo",
            contact_email="operations@palmhills.example",
            contact_phone="+20 2 3827 0000",
            settings={"auto_open_barrier": True, "allow_face_only_entry": True},
        )
        session.add(compound)
        await session.flush()

        # ------------------------------------------------------------- accounts
        officer = User(
            email="officer@gatevision.app",
            hashed_password=hash_password("Officer@12345"),
            full_name="Omar Security",
            phone="+20 100 111 2222",
            role=UserRole.SECURITY_OFFICER,
            compound_id=compound.id,
        )
        resident_user = User(
            email="ahmed@gatevision.app",
            hashed_password=hash_password("Resident@12345"),
            full_name="Ahmed Hassan",
            phone="+20 100 123 4567",
            role=UserRole.RESIDENT,
            compound_id=compound.id,
        )
        session.add_all([officer, resident_user])
        await session.flush()

        # ---------------------------------------------------------------- gates
        entry_gate = Gate(
            compound_id=compound.id,
            name="Main Entrance",
            code="GATE-IN",
            direction=GateDirection.ENTRY,
            status=GateStatus.ONLINE,
            location="North access road",
            notes="Primary resident and visitor entrance",
        )
        exit_gate = Gate(
            compound_id=compound.id,
            name="Main Exit",
            code="GATE-OUT",
            direction=GateDirection.EXIT,
            status=GateStatus.ONLINE,
            location="North access road",
        )
        service_gate = Gate(
            compound_id=compound.id,
            name="Service Gate",
            code="GATE-SVC",
            direction=GateDirection.BIDIRECTIONAL,
            status=GateStatus.MAINTENANCE,
            location="South service road",
            notes="Deliveries and maintenance access",
        )
        session.add_all([entry_gate, exit_gate, service_gate])
        await session.flush()

        cameras = [
            Camera(
                gate_id=entry_gate.id,
                name="Entry Lane Camera",
                source_type=CameraSourceType.DEMO,
                source_url="demo://entry-lane",
                fps_limit=2.0,
                position="front",
                status=CameraStatus.OFFLINE,
                notes="Simulated feed (CV_MODE=mock)",
            ),
            Camera(
                gate_id=exit_gate.id,
                name="Exit Lane Camera",
                source_type=CameraSourceType.DEMO,
                source_url="demo://exit-lane",
                fps_limit=2.0,
                position="front",
                status=CameraStatus.OFFLINE,
                notes="Simulated feed (CV_MODE=mock)",
            ),
            Camera(
                gate_id=service_gate.id,
                name="Service Lane Camera",
                source_type=CameraSourceType.RTSP,
                source_url="rtsp://192.168.1.50:554/stream1",
                fps_limit=3.0,
                position="rear",
                is_active=False,
                status=CameraStatus.DISABLED,
                notes="A real RTSP camera can be enabled here",
            ),
        ]
        session.add_all(cameras)

        # ---------------------------------------------------------------- units
        unit_specs = [
            ("A", "101", 1, UnitType.APARTMENT, 3, 180),
            ("A", "102", 1, UnitType.APARTMENT, 2, 140),
            ("B", "204", 2, UnitType.APARTMENT, 3, 195),
            ("C", "305", 3, UnitType.APARTMENT, 4, 220),
            ("V", "07", 0, UnitType.VILLA, 5, 420),
            ("D", "410", 4, UnitType.APARTMENT, 2, 135),
        ]
        units: dict[str, Unit] = {}
        for building, number, floor, unit_type, bedrooms, area in unit_specs:
            unit = Unit(
                compound_id=compound.id,
                building=building,
                unit_number=number,
                floor=floor,
                unit_type=unit_type,
                status=UnitStatus.OCCUPIED,
                bedrooms=bedrooms,
                area_sqm=area,
            )
            units[f"{building}-{number}"] = unit
            session.add(unit)
        await session.flush()

        # ------------------------------------------------------------ residents
        residents = {
            "ahmed": Resident(
                compound_id=compound.id,
                unit_id=units["A-101"].id,
                user_id=resident_user.id,
                full_name="Ahmed Hassan",
                national_id="28410201101234",
                phone="+20 100 123 4567",
                email="ahmed@gatevision.app",
                role_in_unit=ResidentRelationship.OWNER,
                status=ResidentStatus.ACTIVE,
                is_primary=True,
                move_in_date=date(2021, 3, 1),
            ),
            "salma": Resident(
                compound_id=compound.id,
                unit_id=units["A-101"].id,
                full_name="Salma Hassan",
                national_id="29005150105432",
                phone="+20 100 234 5678",
                role_in_unit=ResidentRelationship.FAMILY,
                status=ResidentStatus.ACTIVE,
                move_in_date=date(2021, 3, 1),
            ),
            "mona": Resident(
                compound_id=compound.id,
                unit_id=units["B-204"].id,
                full_name="Mona Adel",
                national_id="29508120109876",
                phone="+20 101 345 6789",
                email="mona.adel@example.com",
                role_in_unit=ResidentRelationship.TENANT,
                status=ResidentStatus.ACTIVE,
                is_primary=True,
                move_in_date=date(2022, 9, 15),
            ),
            "karim": Resident(
                compound_id=compound.id,
                unit_id=units["A-102"].id,
                full_name="Karim Nabil",
                national_id="28803070102345",
                phone="+20 102 456 7890",
                role_in_unit=ResidentRelationship.OWNER,
                status=ResidentStatus.ACTIVE,
                is_primary=True,
            ),
            "omar": Resident(
                compound_id=compound.id,
                unit_id=units["C-305"].id,
                full_name="Omar Farouk",
                national_id="28012250107654",
                phone="+20 106 567 8901",
                role_in_unit=ResidentRelationship.OWNER,
                status=ResidentStatus.ACTIVE,
                is_primary=True,
            ),
            "yasmine": Resident(
                compound_id=compound.id,
                unit_id=units["V-07"].id,
                full_name="Yasmine Saad",
                national_id="29206180106543",
                phone="+20 115 678 9012",
                role_in_unit=ResidentRelationship.OWNER,
                status=ResidentStatus.ACTIVE,
                is_primary=True,
            ),
        }
        session.add_all(residents.values())
        await session.flush()

        # ------------------------------------------------------------- vehicles
        vehicles = {
            "ahmed": Vehicle(
                compound_id=compound.id,
                resident_id=residents["ahmed"].id,
                plate_number="CAI 4821",
                plate_normalized=normalize_plate("CAI 4821"),
                make="Toyota",
                model="Corolla",
                color="White",
                year=2022,
                vehicle_type=VehicleType.CAR,
                status=VehicleStatus.ACTIVE,
                sticker_number="R-1001",
                last_seen_at=now_local.astimezone(UTC) - timedelta(hours=5),
            ),
            "karim": Vehicle(
                compound_id=compound.id,
                resident_id=residents["karim"].id,
                plate_number="ALX 2210",
                plate_normalized=normalize_plate("ALX 2210"),
                make="Hyundai",
                model="Elantra",
                color="Silver",
                year=2021,
                vehicle_type=VehicleType.CAR,
                status=VehicleStatus.ACTIVE,
                sticker_number="R-1002",
            ),
            "mona": Vehicle(
                compound_id=compound.id,
                resident_id=residents["mona"].id,
                plate_number="CAI 9173",
                plate_normalized=normalize_plate("CAI 9173"),
                make="Nissan",
                model="Sunny",
                color="Grey",
                year=2020,
                vehicle_type=VehicleType.CAR,
                status=VehicleStatus.ACTIVE,
                sticker_number="R-1003",
            ),
            "omar": Vehicle(
                compound_id=compound.id,
                resident_id=residents["omar"].id,
                plate_number="CAI 1122",
                plate_normalized=normalize_plate("CAI 1122"),
                make="Kia",
                model="Sportage",
                color="Black",
                year=2019,
                vehicle_type=VehicleType.CAR,
                status=VehicleStatus.SUSPENDED,
                notes="Access suspended pending management review",
                sticker_number="R-1004",
            ),
            "yasmine": Vehicle(
                compound_id=compound.id,
                resident_id=residents["yasmine"].id,
                plate_number="MN 6644",
                plate_normalized=normalize_plate("MN 6644"),
                make="MG",
                model="ZS",
                color="Red",
                year=2023,
                vehicle_type=VehicleType.CAR,
                status=VehicleStatus.ACTIVE,
                is_inside=True,
                sticker_number="R-1005",
                last_seen_at=now_local.astimezone(UTC) - timedelta(hours=3),
            ),
            "visitor_nadia": Vehicle(
                compound_id=compound.id,
                plate_number="GZ 5520",
                plate_normalized=normalize_plate("GZ 5520"),
                make="Toyota",
                model="Hiace",
                color="White",
                year=2018,
                vehicle_type=VehicleType.VAN,
                status=VehicleStatus.ACTIVE,
            ),
            "visitor_youssef": Vehicle(
                compound_id=compound.id,
                plate_number="GZ 7711",
                plate_normalized=normalize_plate("GZ 7711"),
                make="Chevrolet",
                model="Optra",
                color="Blue",
                year=2017,
                vehicle_type=VehicleType.CAR,
                status=VehicleStatus.ACTIVE,
                is_inside=True,
                last_seen_at=now_local.astimezone(UTC) - timedelta(hours=1),
            ),
        }
        session.add_all(vehicles.values())
        await session.flush()

        # ------------------------------------------------------------- visitors
        nadia = Visitor(
            compound_id=compound.id,
            host_unit_id=units["A-101"].id,
            host_resident_id=residents["ahmed"].id,
            full_name="Nadia Kamal",
            national_id="29704120101111",
            phone="+20 122 334 4556",
            email="nadia.kamal@example.com",
            company="Aramex",
            purpose="Family visit",
            status=VisitorStatus.APPROVED,
            expected_arrival=now_local.astimezone(UTC) + timedelta(hours=1),
            created_by_id=resident_user.id,
            notes="Weekly family visit",
        )
        youssef = Visitor(
            compound_id=compound.id,
            host_unit_id=units["B-204"].id,
            host_resident_id=residents["mona"].id,
            full_name="Youssef Adel",
            national_id="29311230107654",
            phone="+20 128 445 5667",
            company="Cairo Electrical",
            purpose="Maintenance visit",
            status=VisitorStatus.CHECKED_IN,
            expected_arrival=now_local.astimezone(UTC) - timedelta(hours=2),
            actual_arrival=now_local.astimezone(UTC) - timedelta(hours=1, minutes=30),
        )
        session.add_all([nadia, youssef])
        await session.flush()

        permits = [
            Permit(
                compound_id=compound.id,
                visitor_id=nadia.id,
                vehicle_id=vehicles["visitor_nadia"].id,
                host_unit_id=units["A-101"].id,
                host_resident_id=residents["ahmed"].id,
                permit_code=_permit_code("PMT-VIS"),
                permit_type=PermitType.VISITOR,
                status=PermitStatus.ACTIVE,
                start_at=now_local.astimezone(UTC) - timedelta(hours=2),
                end_at=now_local.astimezone(UTC) + timedelta(hours=8),
                max_entries=100,
                entries_used=0,
                issued_by_id=officer.id,
            ),
            Permit(
                compound_id=compound.id,
                visitor_id=youssef.id,
                vehicle_id=vehicles["visitor_youssef"].id,
                host_unit_id=units["B-204"].id,
                host_resident_id=residents["mona"].id,
                permit_code=_permit_code("PMT-VIS"),
                permit_type=PermitType.CONTRACTOR,
                status=PermitStatus.ACTIVE,
                start_at=now_local.astimezone(UTC) - timedelta(hours=3),
                end_at=now_local.astimezone(UTC) + timedelta(hours=5),
                max_entries=2,
                entries_used=1,
                issued_by_id=officer.id,
            ),
        ]
        session.add_all(permits)

        # --------------------------------------------------------- blacklists
        blocked_embedding = FaceEmbedding(
            compound_id=compound.id,
            resident_id=None,
            embedding=list(deterministic_embedding("person:blocked")),
            dimension=512,
            model_name="buffalo_l",
            quality=88.5,
            image_url=await self._save_face("Zaki Mahmoud"),
            source=EmbeddingSource.ENROLLMENT,
            is_active=True,
        )
        session.add(blocked_embedding)
        await session.flush()

        session.add_all(
            [
                BlacklistEntry(
                    compound_id=compound.id,
                    entry_type=BlacklistEntryType.PLATE,
                    plate_number="SUZ 7788",
                    plate_normalized=normalize_plate("SUZ 7788"),
                    reason=BlacklistReason.THEFT,
                    description="Vehicle reported stolen — do not grant access",
                    is_active=True,
                    created_by_id=admin.id if admin else None,
                ),
                BlacklistEntry(
                    compound_id=compound.id,
                    entry_type=BlacklistEntryType.FACE,
                    face_embedding_id=blocked_embedding.id,
                    person_name="Zaki Mahmoud",
                    national_id="27904040109876",
                    reason=BlacklistReason.TRESPASSING,
                    description="Banned after repeated trespassing incidents",
                    is_active=True,
                    created_by_id=admin.id if admin else None,
                ),
            ]
        )

        # -------------------------------------------------------------- faces
        face_keys = {
            "ahmed": "resident:ahmed",
            "mona": "resident:mona",
            "yasmine": "resident:yasmine",
        }
        for key, demo_key in face_keys.items():
            resident = residents[key]
            image_url = await self._save_face(resident.full_name)
            session.add(
                FaceEmbedding(
                    compound_id=compound.id,
                    resident_id=resident.id,
                    embedding=list(deterministic_embedding(demo_key)),
                    dimension=512,
                    model_name="buffalo_l",
                    quality=91.2,
                    image_url=image_url,
                    source=EmbeddingSource.ENROLLMENT,
                    is_active=True,
                    created_by_id=resident_user.id if key == "ahmed" else officer.id,
                )
            )

        # --------------------------------------------------------- demo history
        history = (
            await self._seed_history(
                session=session,
                compound=compound,
                entry_gate=entry_gate,
                exit_gate=exit_gate,
                vehicles=vehicles,
                residents=residents,
                now_local=now_local,
            )
            if with_history
            else 0
        )

        await session.commit()
        logger.info(
            "Demo compound seeded: %s units, %s residents, %s vehicles, %s history logs",
            len(units),
            len(residents),
            len(vehicles),
            history,
        )
        return {
            "created": 1,
            "units": len(units),
            "residents": len(residents),
            "vehicles": len(vehicles),
            "visitors": 2,
            "permits": len(permits),
            "face_embeddings": len(face_keys) + 1,
            "blacklist": 2,
            "access_logs": history,
        }

    async def _save_face(self, name: str) -> str | None:
        try:
            return self.store.save_image(_placeholder_face(name), kind="faces")
        except Exception:  # pragma: no cover - disk issues during seeding
            logger.warning("Could not persist demo face image for %s", name)
            return None

    async def _seed_history(
        self,
        *,
        session: AsyncSession,
        compound: Compound,
        entry_gate: Gate,
        exit_gate: Gate,
        vehicles: dict[str, Vehicle],
        residents: dict[str, Resident],
        now_local: datetime,
    ) -> int:
        rng = random.Random(20241031)
        known_plates = [
            ("CAI 4821", vehicles["ahmed"].id, residents["ahmed"].id),
            ("ALX 2210", vehicles["karim"].id, residents["karim"].id),
            ("CAI 9173", vehicles["mona"].id, residents["mona"].id),
            ("CAI 1122", vehicles["omar"].id, residents["omar"].id),
            ("MN 6644", vehicles["yasmine"].id, residents["yasmine"].id),
            ("GZ 5520", vehicles["visitor_nadia"].id, None),
            ("GZ 7711", vehicles["visitor_youssef"].id, None),
        ]
        unknown_plates = ["ALX 3344", "SUZ 7788", "SHB 1290", "DK 8842", "MNF 3321"]
        peak_hours = [7, 8, 9, 10, 13, 16, 17, 18, 19, 20]
        created = 0
        total_days = 7
        for day_index in range(total_days):
            event_date: date = (now_local - timedelta(days=day_index)).date()
            events_for_day = rng.randint(16, 26)
            for _ in range(events_for_day):
                hour = rng.choice(peak_hours if rng.random() < 0.7 else list(range(24)))
                moment_local = datetime.combine(
                    event_date, time(hour, rng.randint(0, 59), rng.randint(0, 59)), tzinfo=DEMO_TIMEZONE
                )
                if moment_local > now_local:
                    moment_local = now_local - timedelta(minutes=rng.randint(2, 180))
                occurred_at = moment_local.astimezone(UTC)
                direction = (
                    AccessDirection.ENTRY if rng.random() < 0.56 else AccessDirection.EXIT
                )
                gate = entry_gate if direction == AccessDirection.ENTRY else exit_gate
                roll = rng.random()
                if roll < 0.7:
                    decision = AccessDecision.ALLOW
                    reason_code, reason = "registered_vehicle", "Registered resident vehicle"
                    method = AccessMethod.PLATE
                elif roll < 0.83:
                    decision = AccessDecision.UNKNOWN
                    reason_code, reason = "unknown_plate", "Plate is not registered in this compound"
                    method = AccessMethod.PLATE
                elif roll < 0.93:
                    decision = AccessDecision.DENY
                    reason_code, reason = "blacklist_plate", "Vehicle plate is on the blacklist"
                    method = AccessMethod.PLATE
                else:
                    decision = AccessDecision.REVIEW
                    reason_code = "known_face_unknown_vehicle"
                    reason = "Recognised resident in an unregistered vehicle"
                    method = AccessMethod.COMBINED

                if decision == AccessDecision.ALLOW or rng.random() < 0.4:
                    plate, vehicle_id, resident_id = rng.choice(known_plates)
                else:
                    plate = rng.choice(unknown_plates)
                    vehicle_id, resident_id = None, None
                if decision == AccessDecision.ALLOW and plate == "CAI 1122":
                    decision = AccessDecision.DENY
                    reason_code, reason = "vehicle_suspended", "Vehicle access is suspended"
                if decision == AccessDecision.DENY and plate not in {"SUZ 7788", "CAI 1122"}:
                    plate = "SUZ 7788"
                    vehicle_id, resident_id = None, None
                    reason_code, reason = "blacklist_plate", "Vehicle plate is on the blacklist"

                face_detected = rng.random() < 0.45
                face_matched = face_detected and decision in {
                    AccessDecision.ALLOW,
                    AccessDecision.REVIEW,
                }
                log = AccessLog(
                    compound_id=compound.id,
                    gate_id=gate.id,
                    direction=direction,
                    occurred_at=occurred_at,
                    decision=decision,
                    reason_code=reason_code,
                    reason=reason,
                    access_method=method,
                    plate_number=plate,
                    plate_normalized=normalize_plate(plate),
                    plate_confidence=round(rng.uniform(0.72, 0.99), 3),
                    face_similarity=round(rng.uniform(0.52, 0.93), 3) if face_matched else None,
                    vehicle_id=vehicle_id,
                    resident_id=resident_id if face_matched or vehicle_id else None,
                    visitor_id=None,
                    gate_opened=decision == AccessDecision.ALLOW,
                )
                session.add(log)
                await session.flush()
                session.add(
                    DetectionEvent(
                        compound_id=compound.id,
                        gate_id=gate.id,
                        occurred_at=occurred_at,
                        event_type=DetectionType.COMBINED if face_detected else DetectionType.PLATE,
                        plate_text=plate,
                        plate_confidence=log.plate_confidence,
                        plate_bbox={"x1": 420, "y1": 470, "x2": 640, "y2": 525},
                        face_detected=face_detected,
                        face_matched=face_matched,
                        face_similarity=log.face_similarity,
                        matched_resident_id=resident_id if face_matched else None,
                        matched_vehicle_id=vehicle_id,
                        decision=decision,
                        decision_reason=reason,
                        access_log_id=log.id,
                        vision_engine="seed-history",
                        processing_ms=rng.randint(38, 190),
                        raw_payload={"seeded": True},
                    )
                )
                created += 1

        # A few events in the last two hours guarantee the "today" widgets are
        # populated right after seeding, even around midnight/local timezone.
        recent_plates = [
            ("CAI 4821", vehicles["ahmed"].id, residents["ahmed"].id, AccessDecision.ALLOW),
            ("GZ 5520", vehicles["visitor_nadia"].id, None, AccessDecision.ALLOW),
            ("ALX 3344", None, None, AccessDecision.UNKNOWN),
            ("CAI 9173", vehicles["mona"].id, residents["mona"].id, AccessDecision.ALLOW),
            ("SUZ 7788", None, None, AccessDecision.DENY),
            ("ALX 2210", vehicles["karim"].id, residents["karim"].id, AccessDecision.ALLOW),
        ]
        for index, (plate, vehicle_id, resident_id, decision) in enumerate(recent_plates):
            direction = AccessDirection.ENTRY if index % 3 != 2 else AccessDirection.EXIT
            gate = entry_gate if direction == AccessDirection.ENTRY else exit_gate
            occurred_at = now_local.astimezone(UTC) - timedelta(
                minutes=rng.randint(3, 110), seconds=rng.randint(0, 59)
            )
            reason_code = {
                AccessDecision.ALLOW: "registered_vehicle",
                AccessDecision.UNKNOWN: "unknown_plate",
                AccessDecision.DENY: "blacklist_plate",
            }[decision]
            reason = {
                AccessDecision.ALLOW: "Registered resident vehicle",
                AccessDecision.UNKNOWN: "Plate is not registered in this compound",
                AccessDecision.DENY: "Vehicle plate is on the blacklist",
            }[decision]
            log = AccessLog(
                compound_id=compound.id,
                gate_id=gate.id,
                direction=direction,
                occurred_at=occurred_at,
                decision=decision,
                reason_code=reason_code,
                reason=reason,
                access_method=AccessMethod.PLATE,
                plate_number=plate,
                plate_normalized=normalize_plate(plate),
                plate_confidence=round(rng.uniform(0.8, 0.99), 3),
                vehicle_id=vehicle_id,
                resident_id=resident_id,
                gate_opened=decision == AccessDecision.ALLOW,
            )
            session.add(log)
            await session.flush()
            session.add(
                DetectionEvent(
                    compound_id=compound.id,
                    gate_id=gate.id,
                    occurred_at=occurred_at,
                    event_type=DetectionType.PLATE,
                    plate_text=plate,
                    plate_confidence=log.plate_confidence,
                    decision=decision,
                    decision_reason=reason,
                    access_log_id=log.id,
                    vision_engine="seed-history",
                    processing_ms=rng.randint(38, 130),
                    raw_payload={"seeded": True, "recent": True},
                )
            )
            created += 1
        return created


seed_service = SeedService()


async def seed_demo_data(with_history: bool = True) -> dict[str, int]:
    """Seed the demo dataset using a fresh session."""
    from app.db.session import session_scope

    async with session_scope() as session:
        return await seed_service.seed_demo(session, with_history=with_history)
