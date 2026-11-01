"""Scripted OCR reader used by the demo pipeline and tests."""

from __future__ import annotations

from app.cv.types import BoundingBox, Image, PlateReading


class MockPlateReader:
    """Returns the plate text injected by the demo camera source."""

    name = "mock-ocr"

    def __init__(self) -> None:
        self._frame_meta: dict[str, object] = {}

    def set_frame_meta(self, meta: dict[str, object] | None) -> None:
        self._frame_meta = meta or {}

    def read(self, image: Image, bbox: BoundingBox) -> PlateReading | None:
        text = self._frame_meta.get("plate_text")
        if not isinstance(text, str) or not text.strip():
            return None
        confidence = float(self._frame_meta.get("plate_confidence", 0.94))  # type: ignore[arg-type]
        return PlateReading(
            text=text,
            confidence=max(0.0, min(confidence, 1.0)),
            bbox=bbox,
            engine=self.name,
            raw_text=text,
        )

    def warmup(self) -> None:
        return None
