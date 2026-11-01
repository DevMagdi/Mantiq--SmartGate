"""Detection helpers shared by real and mock plate/face implementations."""

from __future__ import annotations

import hashlib
import re
from typing import Sequence

import cv2
import numpy as np

from app.cv.types import BoundingBox, Image

ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_ARABIC_TRANSLATION = {ord(ch): str(idx) for idx, ch in enumerate(ARABIC_DIGITS)}
_OCR_KEEP = re.compile(r"[^A-Z0-9\u0600-\u06FF]")

# Frequent OCR confusions on Gulf/Egyptian plates. Applied only when generating
# *alternative lookup keys* so a single misread character does not lose a match.
_CONFUSIONS = str.maketrans({"O": "0", "Q": "0", "I": "1", "L": "1", "S": "5", "B": "8"})
_REVERSE_CONFUSIONS = str.maketrans({"0": "O", "1": "I", "5": "S", "8": "B"})


def clean_plate_text(raw: str) -> str:
    """Uppercase, drop separators and normalise Arabic-Indic digits."""
    text = raw.translate(_ARABIC_TRANSLATION).upper()
    text = _OCR_KEEP.sub("", text)
    return text.strip()


def normalize_plate(text: str | None) -> str:
    """Normalise a plate into the canonical identity key.

    The canonical key keeps letters intact (``CAI 4821`` → ``CAI4821``) so that
    stored registrations stay human-recognisable. OCR ambiguity is handled at
    lookup time by :func:`plate_variants`.
    """
    if not text:
        return ""
    return clean_plate_text(text)


def plate_variants(text: str | None) -> set[str]:
    """Return the canonical key plus common OCR-confusion alternatives."""
    base = normalize_plate(text)
    if not base:
        return set()
    variants = {base, base.translate(_CONFUSIONS), base.translate(_REVERSE_CONFUSIONS)}
    return {variant for variant in variants if variant}


def format_plate(text: str | None) -> str:
    """Return a human-friendly plate (``cai-4821`` → ``CAI 4821``)."""
    cleaned = clean_plate_text(text or "")
    tokens = re.findall(r"[A-Z\u0600-\u06FF]+|\d+", cleaned)
    return " ".join(tokens) if tokens else cleaned


def plate_match_key(text: str | None) -> str:
    """Alias kept explicit for readability at call sites."""
    return normalize_plate(text)


def valid_plate_candidate(text: str, min_length: int = 3) -> bool:
    """Reject obviously malformed OCR output."""
    cleaned = clean_plate_text(text)
    if len(cleaned) < min_length:
        return False
    digits = sum(ch.isdigit() for ch in cleaned)
    letters = sum(ch.isalpha() for ch in cleaned)
    return digits >= 1 and letters >= 1


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
