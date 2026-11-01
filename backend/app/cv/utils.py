"""Detection helpers shared by real and mock plate/face implementations."""

from __future__ import annotations

import hashlib
from typing import Sequence

import cv2
import numpy as np

from app.cv.types import BoundingBox, Image

from app.cv.plate_rules import (  # noqa: F401 - re-exported for existing imports
    ARABIC_INDIC_DIGITS as ARABIC_DIGITS,
    MAX_PLATE_LENGTH,
    MIN_PLATE_LENGTH,
    PlateParse,
    best_plate_match,
    clean_plate_text,
    describe_plate,
    format_plate,
    format_plate_latin,
    has_arabic,
    levenshtein,
    merge_plate_readings,
    normalize_plate,
    parse_plate,
    plate_display,
    plate_similarity,
    plate_variants,
    quality_score,
    transliterate_plate,
    valid_plate_candidate,
)


def plate_match_key(text: str | None) -> str:
    """Alias kept explicit for readability at call sites."""
    return normalize_plate(text)


def resize_for_inference(image: Image, width: int) -> Image:
    """Downscale a frame so inference stays within the configured budget."""
    if width <= 0 or image.shape[1] <= width:
        return image
    ratio = width / image.shape[1]
    return cv2.resize(image, (width, max(1, int(image.shape[0] * ratio))), interpolation=cv2.INTER_AREA)


def enhance_plate_crop(crop: Image, target_height: int = 96) -> Image:
    """Upscale and contrast-normalise a plate crop for OCR engines."""
    if crop.size == 0:
        return crop
    height, width = crop.shape[:2]
    scale = max(2.0, target_height / max(1, height))
    resized = cv2.resize(
        crop, (max(1, int(width * scale)), max(1, int(height * scale))), interpolation=cv2.INTER_CUBIC
    )
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY) if resized.ndim == 3 else resized
    gray = cv2.bilateralFilter(gray, 9, 75, 75)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    return cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)


def otsu_variants(crop: Image) -> list[Image]:
    """Return thresholded variants that often improve OCR recall."""
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    adaptive = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 9
    )
    return [crop, cv2.cvtColor(otsu, cv2.COLOR_GRAY2BGR), cv2.cvtColor(adaptive, cv2.COLOR_GRAY2BGR)]


def mean_brightness(image: Image) -> float:
    """Return the mean luma of a frame (0-255), used for night detection."""
    if image.size == 0:
        return 0.0
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    return float(gray.mean())


def enhance_low_light(image: Image, clip_limit: float = 2.5) -> Image:
    """Contrast-stretch a night/IR frame before detection.

    Entrance cameras in Egyptian compounds are usually lit by IR after sunset;
    the resulting frames are dark and low-contrast, which destroys both the
    plate detector and OCR. A per-channel CLAHE in LAB space lifts the plate
    without clipping the highlights of headlights.
    """
    if image.size == 0:
        return image
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    luma, a_channel, b_channel = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=max(1.0, clip_limit), tileGridSize=(8, 8))
    merged = cv2.merge((clahe.apply(luma), a_channel, b_channel))
    return cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)


def frame_signature(image: Image, size: int = 16) -> bytes:
    """Return a compact perceptual signature used to detect a frozen stream."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    small = cv2.resize(gray, (size, size), interpolation=cv2.INTER_AREA)
    return small.tobytes()


def blur_score(crop: Image) -> float:
    """Laplacian variance; higher is sharper (used for enrollment quality)."""
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def normalize_embedding(values: Sequence[float]) -> tuple[float, ...]:
    """L2-normalise an embedding so cosine similarity is a dot product."""
    vector = np.asarray(values, dtype=np.float32)
    norm = float(np.linalg.norm(vector))
    if norm <= 0:
        return tuple(float(v) for v in vector)
    return tuple(float(v) for v in (vector / norm))


def deterministic_embedding(key: str, dimension: int = 512) -> tuple[float, ...]:
    """Generate a stable pseudo-embedding for a key.

    Used exclusively by mock engines (offline demo, tests). Real deployments
    always use InsightFace vectors.
    """
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    seed = int.from_bytes(digest[:8], "big", signed=False)
    rng = np.random.default_rng(seed)
    return normalize_embedding(rng.standard_normal(dimension).astype(np.float32))


def image_embedding(image: Image, dimension: int = 512) -> tuple[float, ...]:
    """Deterministic embedding derived from image content (mock engine only)."""
    resized = cv2.resize(image, (32, 32), interpolation=cv2.INTER_AREA)
    payload = hashlib.sha256(resized.tobytes()).hexdigest()
    return deterministic_embedding(payload, dimension=dimension)


def detector_box_from_meta(meta: dict[str, object]) -> BoundingBox | None:
    """Read a scripted plate box injected by the demo camera source."""
    raw = meta.get("plate_bbox")
    if isinstance(raw, dict):
        try:
            return BoundingBox(int(raw["x1"]), int(raw["y1"]), int(raw["x2"]), int(raw["y2"]))
        except (KeyError, TypeError, ValueError):
            return None
    return None


def face_boxes_from_meta(meta: dict[str, object]) -> list[BoundingBox]:
    """Read scripted face boxes injected by the demo camera source."""
    boxes: list[BoundingBox] = []
    raw_list = meta.get("face_bboxes")
    if isinstance(raw_list, list):
        for raw in raw_list:
            if isinstance(raw, dict):
                try:
                    boxes.append(
                        BoundingBox(int(raw["x1"]), int(raw["y1"]), int(raw["x2"]), int(raw["y2"]))
                    )
                except (KeyError, TypeError, ValueError):
                    continue
    return boxes
