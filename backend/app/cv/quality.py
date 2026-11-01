"""Enrollment quality gates for faces (and reusable image checks).

A bad enrollment poisons the gallery: a blurry, tiny or sideways photo makes the
resident fail at the gate for months.  These checks run *before* the embedding
is stored and return an actionable report that the dashboard shows to the
operator.

All thresholds come from :class:`app.services.compound_policy.VisionPolicy`, so
each compound can be as strict as it needs to be.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

import cv2
import numpy as np

from app.cv.types import BoundingBox, Image
from app.cv.utils import blur_score
from app.services.compound_policy import VisionPolicy

ERROR = "error"
WARNING = "warning"


@dataclass(frozen=True, slots=True)
class QualityIssue:
    """One failed check, with a message written for a non-engineer."""

    code: str
    message: str
    severity: str = ERROR
    hint: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "hint": self.hint,
        }


@dataclass(frozen=True, slots=True)
class FaceQualityReport:
    """Outcome of the enrollment pre-flight checks."""

    passed: bool
    score: float
    face_count: int
    width: int
    height: int
    face_ratio: float
    blur: float
    brightness: float
    issues: tuple[QualityIssue, ...] = field(default_factory=tuple)
    duplicate_similarity: float | None = None

    @property
    def errors(self) -> list[QualityIssue]:
        return [issue for issue in self.issues if issue.severity == ERROR]

    @property
    def warnings(self) -> list[QualityIssue]:
        return [issue for issue in self.issues if issue.severity == WARNING]

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "score": self.score,
            "face_count": self.face_count,
            "width": self.width,
            "height": self.height,
            "face_ratio": round(self.face_ratio, 4),
            "blur": round(self.blur, 2),
            "brightness": round(self.brightness, 2),
            "duplicate_similarity": (
                round(self.duplicate_similarity, 4)
                if self.duplicate_similarity is not None
                else None
            ),
            "issues": [issue.as_dict() for issue in self.issues],
        }


def _brightness(crop: Image) -> float:
    if crop.size == 0:
        return 0.0
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    return float(np.mean(gray))


def _sharpness(crop: Image) -> float:
    return blur_score(crop) if crop.size else 0.0


def assess_face_image(
    image: Image,
    faces: Sequence[BoundingBox],
    policy: VisionPolicy | None = None,
    *,
    duplicate_similarity: float | None = None,
) -> FaceQualityReport:
    """Evaluate an enrollment photo against the compound's vision policy.

    Returns a report instead of raising so callers can decide between rejecting,
    warning, or accepting with a low quality flag (e.g. re-enrollment).
    """
    rules = policy or VisionPolicy()
    height, width = image.shape[:2]
    issues: list[QualityIssue] = []

    if min(width, height) < rules.face_min_resolution:
        issues.append(
            QualityIssue(
                code="low_resolution",
                message=(
                    f"Image is {width}×{height}px; at least "
                    f"{rules.face_min_resolution}px on the short side is required."
                ),
                hint="Use the original camera photo or a modern phone camera.",
            )
        )

    face_count = len(faces)
    if face_count == 0:
        issues.append(
            QualityIssue(
                code="no_face",
                message="No face was detected in the photo.",
                hint="Face the camera directly, with the whole face visible and good lighting.",
            )
        )

    face_ratio = 0.0
    face_blur = _sharpness(image)
    face_brightness = _brightness(image)
    if faces:
        primary = _largest_face(faces)
        crop = primary.crop(image)
        face_ratio = primary.area / float(max(1, width * height))
        face_blur = _sharpness(crop)
        face_brightness = _brightness(crop)
        if face_count > 1:
            issues.append(
                QualityIssue(
                    code="multiple_faces",
                    message=f"{face_count} faces were detected; enrollment needs exactly one.",
                    hint="Crop the photo to the resident alone, or retake it.",
                )
            )
        if face_ratio < rules.face_min_face_ratio:
            issues.append(
                QualityIssue(
                    code="face_too_small",
                    message=(
                        f"The face covers {face_ratio * 100:.1f}% of the frame "
                        f"(minimum {rules.face_min_face_ratio * 100:.0f}%)."
                    ),
                    hint="Step closer to the camera or crop the photo.",
                )
            )
        aspect = primary.aspect_ratio
        if aspect and not 0.55 <= aspect <= 1.8:
            issues.append(
                QualityIssue(
                    code="face_distorted",
                    message=f"Unexpected face shape (aspect {aspect:.2f}).",
                    severity=WARNING,
                    hint="Avoid extreme angles or stretched crops.",
                )
            )
        if face_blur < rules.face_min_blur:
            issues.append(
                QualityIssue(
                    code="blurry",
                    message=(
                        f"The face is too soft (sharpness {face_blur:.0f}, "
                        f"minimum {rules.face_min_blur:.0f})."
                    ),
                    hint="Hold still, clean the lens and avoid motion blur.",
                )
            )
        if face_brightness < rules.face_min_brightness:
            issues.append(
                QualityIssue(
                    code="too_dark",
                    message=f"The face is under-exposed (brightness {face_brightness:.0f}).",
                    hint="Face a window or turn on a light.",
                )
            )
        elif face_brightness > rules.face_max_brightness:
            issues.append(
                QualityIssue(
                    code="too_bright",
                    message=f"The face is over-exposed (brightness {face_brightness:.0f}).",
                    hint="Avoid direct sunlight or camera flash.",
                )
            )

    if duplicate_similarity is not None and duplicate_similarity >= rules.duplicate_similarity_threshold:
        issues.append(
            QualityIssue(
                code="duplicate_face",
                message=(
                    f"This photo is {duplicate_similarity * 100:.1f}% similar to an "
                    "existing enrollment for the resident."
                ),
                severity=ERROR if rules.reject_duplicate_enrollment else WARNING,
                hint="Enroll a different angle/photo, or replace the existing one.",
            )
        )

    score = 100.0
    for issue in issues:
        score -= 35.0 if issue.severity == ERROR else 10.0
    score = round(max(0.0, min(100.0, score)), 2)
    passed = not any(issue.severity == ERROR for issue in issues) and score >= rules.face_min_quality
    if not passed and not issues:
        issues.append(
            QualityIssue(
                code="low_quality_score",
                message=f"Quality score {score:.0f} is below the required {rules.face_min_quality:.0f}.",
                hint="Retake the photo with better light and framing.",
            )
        )

    return FaceQualityReport(
        passed=passed,
        score=score,
        face_count=face_count,
        width=width,
        height=height,
        face_ratio=face_ratio,
        blur=face_blur,
        brightness=face_brightness,
        issues=tuple(issues),
        duplicate_similarity=duplicate_similarity,
    )


def _largest_face(faces: Sequence[BoundingBox]) -> BoundingBox:
    return max(faces, key=lambda box: box.area)


__all__ = ["ERROR", "WARNING", "FaceQualityReport", "QualityIssue", "assess_face_image"]
