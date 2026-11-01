"""EasyOCR based plate reader (swappable through ``CV_OCR_ENGINE``)."""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.core.exceptions import VisionEngineError
from app.core.logging import get_logger
from app.cv.types import BoundingBox, Image, PlateReading
from app.cv.utils import clean_plate_text, enhance_plate_crop, otsu_variants, valid_plate_candidate

logger = get_logger(__name__)


class EasyOCRPlateReader:
    """Reads plate crops with EasyOCR and picks the most confident variant.

    Four preprocessing variants (enhanced, raw, Otsu, adaptive threshold) are
    evaluated per crop; the highest confidence candidate that passes the
    alphanumeric sanity check wins. This mirrors the multi-pass strategy used by
    production ANPR systems and materially improves recall on night frames.
    """

    name = "easyocr"

    def __init__(
        self,
        languages: list[str] | None = None,
        min_confidence: float | None = None,
        gpu: bool = False,
    ) -> None:
        self.languages = languages or settings.CV_OCR_LANGUAGES or ["en"]
        self.min_confidence = (
            settings.CV_OCR_MIN_CONFIDENCE if min_confidence is None else min_confidence
        )
        self.gpu = gpu
        self._reader: Any | None = None
        self._load_error: str | None = None

    @property
    def load_error(self) -> str | None:
        return self._load_error

    def load(self) -> None:
        """Initialise the EasyOCR reader (downloads models on first use)."""
        if self._reader is not None:
            return
        if self._load_error:
            raise VisionEngineError(self._load_error)
        try:
            import easyocr

            self._reader = easyocr.Reader(self.languages, gpu=self.gpu, verbose=False)
        except ImportError as exc:  # pragma: no cover - dependency guard
            self._load_error = (
                "easyocr is not installed. Install the CV extras: pip install -r requirements-cv.txt"
            )
            raise VisionEngineError(self._load_error) from exc
        except Exception as exc:  # pragma: no cover - model download failure
            self._load_error = f"Failed to initialise EasyOCR: {exc}"
            raise VisionEngineError(self._load_error) from exc
        logger.info("EasyOCR reader ready (languages=%s)", self.languages)

    def read(self, image: Image, bbox: BoundingBox) -> PlateReading | None:
        self.load()
        assert self._reader is not None
        margin_box = bbox.expand(0.04, image)
        base_crop = margin_box.crop(image)
        if base_crop.size == 0:
            return None
        enhanced = enhance_plate_crop(base_crop)
        candidates = [enhanced, *otsu_variants(enhanced)]

        best: PlateReading | None = None
        for variant in candidates:
            try:
                results = self._reader.readtext(variant, detail=1, paragraph=False)
            except Exception as exc:  # pragma: no cover - engine failure
                logger.debug("EasyOCR pass failed: %s", exc)
                continue
            text_parts: list[str] = []
            confidences: list[float] = []
            for _box, text, confidence in results:
                if float(confidence) < self.min_confidence:
                    continue
                cleaned = clean_plate_text(str(text))
                if cleaned:
                    text_parts.append(cleaned)
                    confidences.append(float(confidence))
            if not text_parts:
                continue
            text = "".join(text_parts)
            if not valid_plate_candidate(text):
                continue
            confidence = sum(confidences) / len(confidences)
            if best is None or confidence > best.confidence:
                best = PlateReading(
                    text=text,
                    confidence=confidence,
                    bbox=bbox,
                    engine=self.name,
                    raw_text=" ".join(str(r[1]) for r in results),
                )
        return best

    def warmup(self) -> None:
        import numpy as np

        self.load()
        try:
            self._reader.readtext(np.zeros((32, 96, 3), dtype=np.uint8), detail=1)  # type: ignore[union-attr]
        except Exception:  # pragma: no cover - warmup is best effort
            pass
