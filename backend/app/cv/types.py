"""Computer vision domain types shared across the pipeline."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

import numpy as np
from numpy.typing import NDArray

Image = NDArray[np.uint8]


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """Axis aligned pixel box."""

    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def width(self) -> int:
        return max(0, self.x2 - self.x1)

    @property
    def height(self) -> int:
        return max(0, self.y2 - self.y1)

    @property
    def area(self) -> int:
        return self.width * self.height

    @property
    def aspect_ratio(self) -> float:
        return self.width / self.height if self.height else 0.0

    @property
    def center(self) -> tuple[int, int]:
        return ((self.x1 + self.x2) // 2, (self.y1 + self.y2) // 2)

    def clamp(self, image: Image) -> "BoundingBox":
        """Clamp the box to the image boundaries."""
        height, width = image.shape[:2]
        return BoundingBox(
            x1=max(0, min(self.x1, width - 1)),
            y1=max(0, min(self.y1, height - 1)),
            x2=max(1, min(self.x2, width)),
            y2=max(1, min(self.y2, height)),
        )

    def expand(self, ratio: float, image: Image | None = None) -> "BoundingBox":
        """Grow the box by a ratio of its size (useful for OCR crops)."""
        pad_x = int(self.width * ratio)
        pad_y = int(self.height * ratio)
        box = BoundingBox(self.x1 - pad_x, self.y1 - pad_y, self.x2 + pad_x, self.y2 + pad_y)
        return box.clamp(image) if image is not None else box

    def crop(self, image: Image) -> Image:
        """Return the cropped region of an image."""
        box = self.clamp(image)
        return image[box.y1 : box.y2, box.x1 : box.x2].copy()

    def as_dict(self) -> dict[str, int]:
        return {"x1": self.x1, "y1": self.y1, "x2": self.x2, "y2": self.y2}


@dataclass(frozen=True, slots=True)
class RawFrame:
    """A decoded camera frame with capture metadata."""

    image: Image
    camera_id: uuid.UUID | None
    gate_id: uuid.UUID | None
    source_id: str
    captured_at: datetime
    sequence: int = 0
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PlateDetection:
    """A detected license plate region."""

    bbox: BoundingBox
    confidence: float


@dataclass(frozen=True, slots=True)
class PlateReading:
    """OCR output for a plate crop."""

    text: str
    confidence: float
    bbox: BoundingBox
    engine: str
    raw_text: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "confidence": round(self.confidence, 4),
            "engine": self.engine,
            "bbox": self.bbox.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class FaceDetection:
    """A detected face with an optional 512-d embedding."""

    bbox: BoundingBox
    det_score: float
    embedding: tuple[float, ...] | None = None


@dataclass(frozen=True, slots=True)
class FaceMatch:
    """A face matched against the enrolled gallery."""

    resident_id: uuid.UUID
    embedding_id: uuid.UUID | None
    similarity: float
    bbox: BoundingBox


@dataclass(frozen=True, slots=True)
class VisionResult:
    """Complete output of one pipeline invocation."""

    plate: PlateReading | None
    face: FaceDetection | None
    face_match: FaceMatch | None
    face_embedding: tuple[float, ...] | None
    plate_snapshot_url: str | None
    face_snapshot_url: str | None
    processing_ms: int
    engine: str
    captured_at: datetime
    camera_id: uuid.UUID | None
    gate_id: uuid.UUID | None
    warnings: tuple[str, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def plate_text(self) -> str | None:
        return self.plate.text if self.plate else None

    def as_payload(self) -> dict[str, Any]:
        """Serialise the result for events and the detection API."""
        return {
            "plate_text": self.plate_text,
            "plate_confidence": round(self.plate.confidence, 4) if self.plate else None,
            "plate_snapshot_url": self.plate_snapshot_url,
            "face_detected": self.face is not None,
            "face_matched": self.face_match is not None,
            "face_similarity": round(self.face_match.similarity, 4) if self.face_match else None,
            "face_snapshot_url": self.face_snapshot_url,
            "matched_resident_id": str(self.face_match.resident_id) if self.face_match else None,
            "processing_ms": self.processing_ms,
            "engine": self.engine,
            "warnings": list(self.warnings),
            "captured_at": self.captured_at.isoformat(),
            "camera_id": str(self.camera_id) if self.camera_id else None,
            "gate_id": str(self.gate_id) if self.gate_id else None,
        }


class PlateDetector(Protocol):
    """Finds license plate bounding boxes in a frame."""

    name: str

    def detect(self, image: Image) -> list[PlateDetection]:
        """Return candidate plate boxes ordered by confidence."""


class PlateReader(Protocol):
    """Reads the textual plate number from a plate crop."""

    name: str

    def read(self, image: Image, bbox: BoundingBox) -> PlateReading | None:
        """Return a reading or ``None`` when nothing legible was found."""


class FaceDetector(Protocol):
    """Detects faces and extracts recognition embeddings."""

    name: str

    def detect(self, image: Image) -> list[FaceDetection]:
        """Return faces ordered by detection score."""


class GateActuator(Protocol):
    """Abstraction over the physical barrier controller."""

    async def open(self, gate_code: str, reason: str) -> bool:
        """Command the barrier to open; return ``True`` if accepted."""

    async def close(self, gate_code: str, reason: str) -> bool:
        """Command the barrier to close."""

    async def hold(self, gate_code: str, reason: str) -> bool:
        """Hold the barrier open (manual review)."""
