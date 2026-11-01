"""PaddleOCR based plate reader (alternative to EasyOCR)."""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.core.exceptions import VisionEngineError
from app.core.logging import get_logger
from app.cv.types import BoundingBox, Image, PlateReading
from app.cv.utils import clean_plate_text, enhance_plate_crop, valid_plate_candidate

logger = get_logger(__name__)


class PaddleOCRPlateReader:
    """PaddleOCR wrapper normalising the v2/v3 result formats."""

    name = "paddleocr"

    def __init__(self, languages: list[str] | None = None, min_confidence: float | None = None) -> None:
        self.languages = languages or settings.CV_OCR_LANGUAGES or ["en"]
        self.min_confidence = (
            settings.CV_OCR_MIN_CONFIDENCE if min_confidence is None else min_confidence
        )
        self._engine: Any | None = None
        self._load_error: str | None = None

    @property
    def load_error(self) -> str | None:
        return self._load_error

    def load(self) -> None:
        if self._engine is not None:
            return
        if self._load_error:
            raise VisionEngineError(self._load_error)
        try:
            from paddleocr import PaddleOCR

            lang = self.languages[0]
            try:
                self._engine = PaddleOCR(use_angle_cls=True, lang=lang, show_log=False)
            except (TypeError, ValueError):
                # PaddleOCR 3.x removed show_log/use_angle_cls arguments.
                self._engine = PaddleOCR(lang=lang)
        except ImportError as exc:  # pragma: no cover - dependency guard
            self._load_error = (
                "paddleocr is not installed. Install it separately or use CV_OCR_ENGINE=easyocr."
            )
            raise VisionEngineError(self._load_error) from exc
        except Exception as exc:  # pragma: no cover
            self._load_error = f"Failed to initialise PaddleOCR: {exc}"
            raise VisionEngineError(self._load_error) from exc
        logger.info("PaddleOCR reader ready (lang=%s)", self.languages[0])

    def _run(self, image: Image) -> list[Any]:
        assert self._engine is not None
        engine = self._engine
        attempts = (
            lambda: engine.ocr(image, cls=True),
            lambda: engine.ocr(image),
            lambda: engine.predict(image),
        )
        for attempt in attempts:
            try:
                result = attempt()
            except (TypeError, ValueError):
                continue
            if result:
                return list(result)
        return []

    def read(self, image: Image, bbox: BoundingBox) -> PlateReading | None:
        self.load()
        crop = enhance_plate_crop(bbox.expand(0.04, image).crop(image))
        if crop.size == 0:
            return None
        raw = self._run(crop)
        texts: list[str] = []
        confidences: list[float] = []

        def consume(node: Any) -> None:
            if isinstance(node, (list, tuple)) and len(node) == 2:
                payload, confidence = node
                if isinstance(payload, str) and isinstance(confidence, (int, float)):
                    cleaned = clean_plate_text(payload)
                    if cleaned and float(confidence) >= self.min_confidence:
                        texts.append(cleaned)
                        confidences.append(float(confidence))
                    return
            if isinstance(node, (list, tuple)):
                for child in node:
                    consume(child)

        consume(raw)
        text = "".join(texts)
        if not text or not valid_plate_candidate(text):
            return None
        return PlateReading(
            text=text,
            confidence=sum(confidences) / len(confidences),
            bbox=bbox,
            engine=self.name,
            raw_text=text,
        )

    def warmup(self) -> None:
        import numpy as np

        self.load()
        try:
            self._run(np.zeros((32, 96, 3), dtype=np.uint8))
        except Exception:  # pragma: no cover
            pass
