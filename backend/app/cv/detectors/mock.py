"""Deterministic detectors used for offline demos, CI and unit tests."""

from __future__ import annotations

import numpy as np

from app.cv.types import BoundingBox, FaceDetection, Image, PlateDetection
from app.cv.utils import (
    deterministic_embedding,
    detector_box_from_meta,
    face_boxes_from_meta,
    image_embedding,
)


class MockPlateDetector:
    """Returns the scripted plate box, or a stable synthetic region."""

    name = "mock-plate-detector"

    def __init__(self) -> None:
        self._frame_meta: dict[str, object] = {}

    def set_frame_meta(self, meta: dict[str, object] | None) -> None:
        """Inject demo metadata for the next detection call."""
        self._frame_meta = meta or {}

    def detect(self, image: Image) -> list[PlateDetection]:
        meta_box = detector_box_from_meta(self._frame_meta)
        if meta_box is not None:
            return [PlateDetection(bbox=meta_box.clamp(image), confidence=0.97)]
        height, width = image.shape[:2]
        box = BoundingBox(
            x1=int(width * 0.36), y1=int(height * 0.62), x2=int(width * 0.64), y2=int(height * 0.72)
        )
        return [PlateDetection(bbox=box.clamp(image), confidence=0.55)]

    def warmup(self) -> None:
        import numpy as np

        self.detect(np.zeros((64, 64, 3), dtype=np.uint8))


class MockFaceDetector:
    """Returns scripted faces; falls back to a central synthetic face."""

    name = "mock-face-detector"
    dimension = 512

    def __init__(self) -> None:
        self._frame_meta: dict[str, object] = {}

    def set_frame_meta(self, meta: dict[str, object] | None) -> None:
        """Inject demo metadata for the next detection call."""
        self._frame_meta = meta or {}

    def detect(self, image: Image) -> list[FaceDetection]:
        boxes = face_boxes_from_meta(self._frame_meta)
        keys = self._frame_meta.get("face_keys")
        key_list = keys if isinstance(keys, list) else []
        faces: list[FaceDetection] = []
        for index, box in enumerate(boxes):
            key = str(key_list[index]) if index < len(key_list) else f"face-{index}"
            faces.append(
                FaceDetection(
                    bbox=box.clamp(image),
                    det_score=0.95,
                    embedding=deterministic_embedding(key, dimension=self.dimension),
                )
            )
        if faces:
            return faces
        height, width = image.shape[:2]
        bbox = BoundingBox(
            x1=int(width * 0.42), y1=int(height * 0.18), x2=int(width * 0.58), y2=int(height * 0.46)
        ).clamp(image)
        embedding = image_embedding(bbox.crop(image), dimension=self.dimension)
        return [FaceDetection(bbox=bbox, det_score=0.80, embedding=embedding)]

    def embed(self, image: Image, bbox: BoundingBox | None = None) -> tuple[float, ...] | None:
        """Extract a deterministic embedding for enrollment."""
        crop = bbox.crop(image) if bbox is not None else image
        if crop.size == 0:
            return None
        return image_embedding(crop, dimension=self.dimension)

    def warmup(self) -> None:
        dummy = np.zeros((64, 64, 3), dtype=np.uint8)
        self.detect(dummy)
