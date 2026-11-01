"""Snapshot persistence for detections and face enrollment images."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np

from app.core.config import settings
from app.core.exceptions import VisionEngineError
from app.cv.types import BoundingBox, Image


class SnapshotStore:
    """Writes JPEG crops/frames to the media directory and returns public URLs."""

    def __init__(
        self,
        root: Path | None = None,
        url_prefix: str | None = None,
        jpeg_quality: int | None = None,
    ) -> None:
        self.root = root or settings.MEDIA_ROOT
        self.url_prefix = (url_prefix or settings.MEDIA_URL).rstrip("/")
        self.jpeg_quality = jpeg_quality or settings.CV_SNAPSHOT_QUALITY
        self.root.mkdir(parents=True, exist_ok=True)

    def _relative_path(self, kind: str, extension: str = "jpg") -> Path:
        now = datetime.now(UTC)
        directory = Path(kind) / now.strftime("%Y") / now.strftime("%m") / now.strftime("%d")
        (self.root / directory).mkdir(parents=True, exist_ok=True)
        filename = f"{now.strftime('%H%M%S')}_{uuid.uuid4().hex[:10]}.{extension}"
        return directory / filename

    def save_image(self, image: Image, kind: str = "frames", quality: int | None = None) -> str:
        """Write an image to disk and return its public URL."""
        if image is None or image.size == 0:
            raise VisionEngineError("Cannot persist an empty image")
        relative = self._relative_path(kind)
        target = self.root / relative
        ok, buffer = cv2.imencode(
            ".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality or self.jpeg_quality)]
        )
        if not ok:
            raise VisionEngineError("Failed to encode snapshot as JPEG")
        target.write_bytes(buffer.tobytes())
        return f"{self.url_prefix}/{relative.as_posix()}"

    def save_crop(self, image: Image, bbox: BoundingBox, kind: str = "plates") -> str:
        """Persist a cropped region (plate or face)."""
        crop = bbox.crop(image)
        if crop.size == 0:
            raise VisionEngineError("Cannot persist an empty crop")
        return self.save_image(crop, kind=kind)

    def save_bytes(self, data: bytes, extension: str = "jpg") -> str:
        """Persist already-encoded image bytes (uploads)."""
        relative = self._relative_path("faces", extension=extension)
        (self.root / relative).write_bytes(data)
        return f"{self.url_prefix}/{relative.as_posix()}"

    @staticmethod
    def encode_jpeg(image: Image) -> bytes:
        """Encode an image to JPEG bytes (used for API downloads)."""
        ok, buffer = cv2.imencode(".jpg", np.asarray(image))
        if not ok:
            raise VisionEngineError("Failed to encode image")
        return buffer.tobytes()
