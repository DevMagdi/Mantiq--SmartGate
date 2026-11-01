"""Face enrollment and gallery queries."""

from __future__ import annotations

import asyncio
import uuid

import cv2
import numpy as np
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BadRequestError, NotFoundError, VisionEngineError
from app.core.logging import get_logger
from app.cv.engine import get_vision_engine
from app.cv.gallery import FaceGallery, GalleryEntry
from app.cv.quality import FaceQualityReport, assess_face_image
from app.cv.snapshots import SnapshotStore
from app.models.enums import BlacklistEntryType, EmbeddingSource
from app.models.people import Resident
from app.models.security import BlacklistEntry, FaceEmbedding
from app.schemas.common import Page
from app.schemas.security import FaceGalleryInfo
from app.services.compound_policy import VisionPolicy
from app.services.pagination import PageParams, build_page, count_rows

logger = get_logger(__name__)


def decode_image(data: bytes) -> np.ndarray:
    """Decode raw image bytes into a BGR numpy array."""
    if not data:
        raise BadRequestError("Empty image payload")
    if len(data) > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise BadRequestError(f"Image exceeds the {settings.MAX_UPLOAD_MB}MB limit")
    array = np.frombuffer(data, dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if image is None:
        raise BadRequestError("Unsupported image format; upload a JPEG or PNG file")
    return image


def _as_list(values: object) -> list[float]:
    return [float(value) for value in values]  # type: ignore[union-attr]


class FaceService:
    """Enrollment and management of face embeddings."""

    def __init__(self) -> None:
        self.store = SnapshotStore()

    async def list(
        self,
        session: AsyncSession,
        params: PageParams,
        *,
        compound_id: uuid.UUID | None,
        resident_id: uuid.UUID | None = None,
        is_active: bool | None = None,
        search: str | None = None,
        include_embedding: bool = False,
    ) -> Page[FaceEmbedding]:
        stmt = select(FaceEmbedding)
        if compound_id is not None:
            stmt = stmt.where(FaceEmbedding.compound_id == compound_id)
        if resident_id is not None:
            stmt = stmt.where(FaceEmbedding.resident_id == resident_id)
        if is_active is not None:
            stmt = stmt.where(FaceEmbedding.is_active.is_(is_active))
        if search:
            term = f"%{search.strip().lower()}%"
            stmt = stmt.join(FaceEmbedding.resident).where(
                or_(
                    Resident.full_name.ilike(term),
                    Resident.national_id.ilike(term),
                    Resident.phone.ilike(term),
                )
            )
        total = await count_rows(session, stmt)
        stmt = stmt.order_by(FaceEmbedding.created_at.desc()).offset(params.offset).limit(
            params.page_size
        )
        items = list((await session.execute(stmt)).scalars().unique().all())
        if not include_embedding:
            for item in items:
                # Never ship raw biometric vectors to the browser.
                item.embedding = []  # type: ignore[assignment]
        return build_page(items, total, params)

    async def quality_report(
        self,
        image_data: bytes,
        *,
        policy: VisionPolicy | None = None,
        resident_id: uuid.UUID | None = None,
        session: AsyncSession | None = None,
    ) -> FaceQualityReport:
        """Run the enrollment pre-flight checks without persisting anything."""
        image = decode_image(image_data)
        engine = get_vision_engine()
        faces = await asyncio.to_thread(engine.face_boxes, image)
        rules = policy or VisionPolicy()
        duplicate: float | None = None
        if session is not None and resident_id is not None:
            existing = await self._active_embeddings(session, resident_id)
            if existing:
                try:
                    embedding = await asyncio.to_thread(engine.embedding_for_enrollment, image)
                except VisionEngineError:
                    embedding = None
                if embedding:
                    duplicate = max(
                        (
                            FaceGallery.similarity(_as_list(item.embedding), _as_list(embedding))
                            for item in existing
                        ),
                        default=None,
                    )
        return assess_face_image(image, faces, rules, duplicate_similarity=duplicate)

    async def enroll(
        self,
        session: AsyncSession,
        *,
        compound_id: uuid.UUID,
        resident_id: uuid.UUID,
        image_data: bytes,
        actor_id: uuid.UUID | None,
        overwrite: bool = False,
        source: EmbeddingSource = EmbeddingSource.ENROLLMENT,
        policy: VisionPolicy | None = None,
    ) -> tuple[FaceEmbedding, float | None]:
        resident = await session.get(Resident, resident_id)
        if resident is None or resident.compound_id != compound_id:
            raise BadRequestError("The resident does not belong to this compound")
        rules = policy or VisionPolicy()
        image = decode_image(image_data)
        engine = get_vision_engine()
        try:
            faces = await asyncio.to_thread(engine.face_boxes, image)
            embedding = await asyncio.to_thread(engine.embedding_for_enrollment, image)
        except VisionEngineError as exc:
            raise VisionEngineError(str(exc)) from exc
        if not embedding:
            raise BadRequestError(
                "No face could be detected in the uploaded image. Use a clear, frontal photo.",
                code="no_face_detected",
            )

        existing = await self._active_embeddings(session, resident_id)
        similarity: float | None = None
        if existing:
            similarity = max(
                (
                    FaceGallery.similarity(_as_list(item.embedding), _as_list(embedding))
                    for item in existing
                ),
                default=None,
            )

        report = assess_face_image(image, faces, rules, duplicate_similarity=similarity)
        if not report.passed:
            raise BadRequestError(
                "The photo did not pass the enrollment quality checks.",
                code="enrollment_rejected",
                details=report.as_dict(),
            )
        if len(existing) >= rules.max_embeddings_per_resident and not overwrite:
            raise BadRequestError(
                (
                    f"This resident already has {len(existing)} active embeddings "
                    f"(limit {rules.max_embeddings_per_resident}). "
                    "Re-enroll with overwrite=true to replace them, or remove old photos."
                ),
                code="embedding_limit_reached",
                details=report.as_dict(),
            )

        if overwrite:
            for item in existing:
                item.is_active = False
        image_url = await asyncio.to_thread(self.store.save_image, image, "faces")
        record = FaceEmbedding(
            compound_id=compound_id,
            resident_id=resident_id,
            embedding=list(embedding),
            dimension=len(embedding),
            model_name=engine.status().get("face_engine", settings.CV_FACE_ENGINE),
            quality=report.score,
            image_url=image_url,
            source=source,
            is_active=True,
            created_by_id=actor_id,
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)
        logger.info(
            "Face enrolled for resident %s (dim=%d, similarity=%s)",
            resident_id,
            record.dimension,
            f"{similarity:.3f}" if similarity else "n/a",
        )
        return record, similarity

    async def _active_embeddings(
        self, session: AsyncSession, resident_id: uuid.UUID
    ) -> list[FaceEmbedding]:
        stmt = select(FaceEmbedding).where(
            FaceEmbedding.resident_id == resident_id,
            FaceEmbedding.is_active.is_(True),
        )
        return list((await session.execute(stmt)).scalars().all())

    async def prune(
        self,
        session: AsyncSession,
        *,
        compound_id: uuid.UUID,
        max_per_resident: int,
        dry_run: bool = False,
    ) -> dict[str, int]:
        """Deactivate surplus embeddings, keeping the highest-quality ones.

        Returns counters so the caller can report exactly what happened.
        """
        limit = max(1, max_per_resident)
        stmt = select(FaceEmbedding).where(
            FaceEmbedding.compound_id == compound_id,
            FaceEmbedding.is_active.is_(True),
        )
        records = list((await session.execute(stmt)).scalars().all())
        grouped: dict[uuid.UUID, list[FaceEmbedding]] = {}
        for record in records:
            if record.resident_id is not None:
                grouped.setdefault(record.resident_id, []).append(record)
        deactivated = 0
        kept = 0
        affected_residents = 0
        for items in grouped.values():
            ordered = sorted(items, key=lambda item: item.quality or 0.0, reverse=True)
            kept += min(len(ordered), limit)
            surplus = ordered[limit:]
            if not surplus:
                continue
            affected_residents += 1
            for record in surplus:
                deactivated += 1
                if not dry_run:
                    record.is_active = False
        if not dry_run and deactivated:
            await session.commit()
        logger.info(
            "Face gallery prune (%s): kept=%d deactivated=%d residents=%d",
            "dry-run" if dry_run else "applied",
            kept,
            deactivated,
            affected_residents,
        )
        return {
            "evaluated": len(records),
            "kept": kept,
            "deactivated": deactivated,
            "residents_affected": affected_residents,
            "dry_run": int(dry_run),
        }

    async def get(self, session: AsyncSession, embedding_id: uuid.UUID) -> FaceEmbedding:
        record = await session.get(FaceEmbedding, embedding_id)
        if record is None:
            raise NotFoundError("Face embedding not found", code="embedding_not_found")
        return record

    async def deactivate(self, session: AsyncSession, embedding_id: uuid.UUID) -> FaceEmbedding:
        record = await self.get(session, embedding_id)
        record.is_active = False
        await session.commit()
        await session.refresh(record)
        return record

    async def delete(self, session: AsyncSession, embedding_id: uuid.UUID) -> None:
        record = await self.get(session, embedding_id)
        await session.delete(record)
        await session.commit()

    async def gallery_info(
        self, session: AsyncSession, compound_id: uuid.UUID | None
    ) -> FaceGalleryInfo:
        base = select(FaceEmbedding)
        if compound_id is not None:
            base = base.where(FaceEmbedding.compound_id == compound_id)
        total = await session.scalar(
            select(func.count()).select_from(base.subquery())
        ) or 0
        active = await session.scalar(
            select(func.count()).select_from(base.where(FaceEmbedding.is_active.is_(True)).subquery())
        ) or 0
        residents = await session.scalar(
            select(func.count(func.distinct(FaceEmbedding.resident_id))).where(
                *([] if compound_id is None else [FaceEmbedding.compound_id == compound_id]),
                FaceEmbedding.is_active.is_(True),
                FaceEmbedding.resident_id.is_not(None),
            )
        ) or 0
        engine_status = get_vision_engine().status()
        return FaceGalleryInfo(
            total_embeddings=int(total),
            active_embeddings=int(active),
            enrolled_residents=int(residents),
            model_name=str(engine_status.get("face_engine", settings.CV_FACE_ENGINE)),
            threshold=settings.CV_FACE_SIMILARITY_THRESHOLD,
        )

    async def load_gallery(self, session: AsyncSession, compound_id: uuid.UUID) -> FaceGallery:
        """Load active resident embeddings for image analysis."""
        rows = (
            await session.execute(
                select(FaceEmbedding).where(
                    FaceEmbedding.compound_id == compound_id,
                    FaceEmbedding.is_active.is_(True),
                    FaceEmbedding.resident_id.is_not(None),
                )
            )
        ).scalars().unique().all()
        entries = [
            GalleryEntry(
                resident_id=row.resident_id,  # type: ignore[arg-type]
                embedding=tuple(row.embedding),
                embedding_id=row.id,
                label=row.resident.full_name if row.resident else None,
            )
            for row in rows
            if row.resident_id is not None
        ]
        return FaceGallery(entries)

    async def match_blacklisted_embeddings(
        self,
        session: AsyncSession,
        compound_id: uuid.UUID,
        embedding: tuple[float, ...] | None,
        threshold: float | None = None,
    ) -> frozenset[uuid.UUID]:
        """Return blacklisted face embedding ids that match a detected face."""
        if not embedding:
            return frozenset()
        threshold = settings.CV_FACE_SIMILARITY_THRESHOLD if threshold is None else threshold
        rows = (
            await session.execute(
                select(FaceEmbedding.id, FaceEmbedding.embedding)
                .join(BlacklistEntry, BlacklistEntry.face_embedding_id == FaceEmbedding.id)
                .where(
                    BlacklistEntry.compound_id == compound_id,
                    BlacklistEntry.entry_type == BlacklistEntryType.FACE,
                    BlacklistEntry.is_active.is_(True),
                    FaceEmbedding.is_active.is_(True),
                    or_(
                        BlacklistEntry.expires_at.is_(None),
                        BlacklistEntry.expires_at > func.now(),
                    ),
                )
            )
        ).all()
        if not rows:
            return frozenset()
        gallery = FaceGallery(
            [
                GalleryEntry(resident_id=row[0], embedding=tuple(row[1]), embedding_id=row[0])
                for row in rows
            ]
        )
        match = gallery.match(embedding, threshold=threshold)
        if match is None:
            return frozenset()
        return frozenset({match.embedding_id} if match.embedding_id else set())


face_service = FaceService()
