"""The real-time detection pipeline: plate + face → :class:`VisionResult`."""

from __future__ import annotations

import datetime as dt
import threading
import time
from typing import Any

import cv2
import numpy as np

from app.core.config import settings
from app.core.logging import get_logger
from app.cv.gallery import FaceGallery, FaceGallery as _FaceGallery  # noqa: F401 - re-export
from app.cv.snapshots import SnapshotStore
from app.cv.types import (
    BoundingBox,
    FaceDetection,
    FaceDetector,
    FaceMatch,
    Image,
    PlateDetector,
    PlateReader,
    PlateReading,
    RawFrame,
    VisionResult,
)
from app.cv.utils import clean_plate_text, normalize_plate, valid_plate_candidate

logger = get_logger(__name__)


def _inject_meta(component: object, meta: dict[str, Any]) -> None:
    """Give mock components the scripted metadata of the current frame."""
    setter = getattr(component, "set_frame_meta", None)
    if callable(setter):
        setter(meta)


def _annotate(
    image: Image,
    plate: PlateReading | None,
    face: FaceDetection | None,
    face_match: FaceMatch | None,
) -> Image:
    """Return a copy of the frame with detection overlays burned in."""
    canvas = image.copy()
    if plate is not None:
        box = plate.bbox
        cv2.rectangle(canvas, (box.x1, box.y1), (box.x2, box.y2), (60, 220, 120), 3)
        label = f"{clean_plate_text(plate.text)}  {plate.confidence * 100:.0f}%"
        cv2.putText(
            canvas,
            label,
            (box.x1, max(24, box.y1 - 12)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (60, 220, 120),
            2,
            cv2.LINE_AA,
        )
    if face is not None:
        box = face.bbox
        colour = (80, 200, 255) if face_match is None else (60, 220, 120)
        cv2.rectangle(canvas, (box.x1, box.y1), (box.x2, box.y2), colour, 3)
        label = "face" if face_match is None else f"match {face_match.similarity * 100:.0f}%"
        cv2.putText(
            canvas,
            label,
            (box.x1, max(20, box.y1 - 10)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            colour,
            2,
            cv2.LINE_AA,
        )
    return canvas


class GateVisionPipeline:
    """Combines plate detection/OCR and face recognition for a single frame.

    The pipeline is stateless per invocation except for the shared, thread-safe
    detector instances; the manager serialises inference through the engine's
    lock.
    """

    def __init__(
        self,
        plate_detector: PlateDetector,
        plate_reader: PlateReader,
        face_detector: FaceDetector,
        snapshots: SnapshotStore | None = None,
        *,
        face_threshold: float | None = None,
        plate_confidence: float | None = None,
        ocr_confidence: float | None = None,
    ) -> None:
        self.plate_detector = plate_detector
        self.plate_reader = plate_reader
        self.face_detector = face_detector
        self.snapshots = snapshots or SnapshotStore()
        self.face_threshold = (
            settings.CV_FACE_SIMILARITY_THRESHOLD if face_threshold is None else face_threshold
        )
        self.plate_confidence = (
            settings.CV_PLATE_CONFIDENCE_THRESHOLD if plate_confidence is None else plate_confidence
        )
        self.ocr_confidence = (
            settings.CV_OCR_MIN_CONFIDENCE if ocr_confidence is None else ocr_confidence
        )

    # ------------------------------------------------------------------ plate
    def _read_plate(self, frame: RawFrame) -> tuple[PlateReading | None, list[str]]:
        warnings: list[str] = []
        image = frame.image
        try:
            detections = self.plate_detector.detect(image)
        except Exception as exc:  # pragma: no cover - detector failure
            logger.error("Plate detection failed: %s", exc)
            return None, [f"plate_detector_error:{exc}"]
        detections = [d for d in detections if d.confidence >= self.plate_confidence][:3]
        if not detections:
            return None, warnings

        best: PlateReading | None = None
        best_score = 0.0
        for detection in detections:
            box = detection.bbox
            aspect = box.aspect_ratio
            if not (settings.CV_MIN_PLATE_ASPECT <= aspect <= settings.CV_MAX_PLATE_ASPECT):
                warnings.append(f"plate_aspect_rejected:{aspect:.2f}")
                continue
            try:
                reading = self.plate_reader.read(image, box)
            except Exception as exc:  # pragma: no cover - OCR failure
                logger.error("Plate OCR failed: %s", exc)
                warnings.append("ocr_error")
                continue
            if reading is None:
                continue
            text = clean_plate_text(reading.text)
            if not valid_plate_candidate(text):
                warnings.append("ocr_rejected_text")
                continue
            if reading.confidence < self.ocr_confidence:
                warnings.append(f"ocr_low_confidence:{reading.confidence:.2f}")
                continue
            score = reading.confidence * detection.confidence
            if score > best_score:
                best_score = score
                best = PlateReading(
                    text=text,
                    confidence=reading.confidence,
                    bbox=box,
                    engine=reading.engine,
                    raw_text=reading.raw_text or reading.text,
                )
        return best, warnings

    # ------------------------------------------------------------------- face
    def _read_face(
        self, frame: RawFrame, gallery: FaceGallery | None
    ) -> tuple[FaceDetection | None, FaceMatch | None, list[str]]:
        warnings: list[str] = []
        try:
            faces = self.face_detector.detect(frame.image)
        except Exception as exc:  # pragma: no cover - detector failure
            logger.error("Face detection failed: %s", exc)
            return None, None, [f"face_detector_error:{exc}"]
        if not faces:
            return None, None, warnings
        face = faces[0]
        match: FaceMatch | None = None
        if gallery is not None and len(gallery) and face.embedding is not None:
            gallery_match = gallery.match(face.embedding, self.face_threshold)
            if gallery_match is not None:
                match = FaceMatch(
                    resident_id=gallery_match.resident_id,
                    embedding_id=gallery_match.embedding_id,
                    similarity=gallery_match.similarity,
                    bbox=face.bbox,
                )
        return face, match, warnings

    # --------------------------------------------------------------- pipeline
    def process(
        self,
        frame: RawFrame,
        gallery: FaceGallery | None = None,
        *,
        annotate: bool = True,
        include_face: bool = True,
    ) -> VisionResult:
        """Run plate + face recognition on one frame."""
        started = time.perf_counter()
        meta = frame.meta or {}
        for component in (self.plate_detector, self.plate_reader, self.face_detector):
            _inject_meta(component, meta)

        plate, plate_warnings = self._read_plate(frame)
        face: FaceDetection | None = None
        face_match: FaceMatch | None = None
        face_warnings: list[str] = []
        if include_face:
            face, face_match, face_warnings = self._read_face(frame, gallery)

        snapshot_url: str | None = None
        plate_crop_url: str | None = None
        face_crop_url: str | None = None
        if plate is not None or face is not None:
            annotated = _annotate(frame.image, plate, face, face_match) if annotate else frame.image
            try:
                snapshot_url = self.snapshots.save_image(annotated, kind="snapshots")
                if plate is not None:
                    plate_crop_url = self.snapshots.save_crop(
                        frame.image, plate.bbox.expand(0.08, frame.image), kind="plates"
                    )
                if face is not None:
                    face_crop_url = self.snapshots.save_crop(
                        frame.image, face.bbox.expand(0.12, frame.image), kind="faces"
                    )
            except Exception as exc:  # pragma: no cover - disk failures
                logger.error("Failed to persist snapshots: %s", exc)
                plate_warnings.append("snapshot_write_failed")

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        engine_name = f"{getattr(self.plate_detector, 'name', 'plate')}+{getattr(self.plate_reader, 'name', 'ocr')}"
        return VisionResult(
            plate=plate,
            face=face,
            face_match=face_match,
            face_embedding=face.embedding if face is not None else None,
            plate_snapshot_url=snapshot_url,
            face_snapshot_url=face_crop_url,
            processing_ms=elapsed_ms,
            engine=engine_name,
            captured_at=frame.captured_at,
            camera_id=frame.camera_id,
            gate_id=frame.gate_id,
            warnings=tuple(plate_warnings + face_warnings),
            raw={
                "frame_snapshot_url": snapshot_url,
                "plate_crop_url": plate_crop_url,
                "plate_normalized": normalize_plate(plate.text) if plate else None,
                "source_id": frame.source_id,
                "sequence": frame.sequence,
                "scenario": meta.get("scenario"),
            },
        )

    def analyze_image(
        self, image: Image, gallery: FaceGallery | None = None, meta: dict[str, Any] | None = None
    ) -> VisionResult:
        """Analyse a single uploaded image (manual verification workflow)."""
        now = dt.datetime.now(dt.UTC)
        frame = RawFrame(
            image=image,
            camera_id=None,
            gate_id=None,
            source_id="upload",
            captured_at=now,
            meta=meta or {},
        )
        return self.process(frame, gallery=gallery)


class Deduplicator:
    """Suppress repeated detections of the same plate/face within a cooldown."""

    def __init__(self, cooldown_seconds: float | None = None) -> None:
        self.cooldown = settings.CV_DEDUPE_SECONDS if cooldown_seconds is None else cooldown_seconds
        self._lock = threading.Lock()
        self._seen: dict[str, float] = {}

    def should_emit(self, result: VisionResult) -> bool:
        """Return ``True`` exactly once per key per cooldown window."""
        key: str | None = None
        if result.plate is not None:
            key = f"plate:{normalize_plate(result.plate.text)}"
        elif result.face_match is not None:
            key = f"face:{result.face_match.resident_id}"
        elif result.face is not None:
            key = "face:unknown"
        if key is None:
            return False
        now = time.monotonic()
        with self._lock:
            last = self._seen.get(key)
            if last is not None and now - last < self.cooldown:
                return False
            self._seen[key] = now
            if len(self._seen) > 2000:
                cutoff = now - self.cooldown
                self._seen = {k: v for k, v in self._seen.items() if v >= cutoff}
        return True


def frame_to_jpeg(image: Image, quality: int = 85) -> bytes:
    """Encode a frame as JPEG bytes (used by the preview endpoint)."""
    ok, buffer = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        return np.zeros(0, dtype=np.uint8).tobytes()
    return buffer.tobytes()


__all__ = ["BoundingBox", "Deduplicator", "GateVisionPipeline", "frame_to_jpeg"]
