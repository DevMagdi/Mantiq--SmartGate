"""GateVision computer vision package.

Contains the plate/face detectors, OCR recognizers, the real-time pipeline and
the access decision engine. All computer vision logic lives here; API routers
and services never import OpenCV or model runtimes directly.
"""

from app.cv.engine import VisionEngine, get_vision_engine
from app.cv.gate_controller import (
    AccessDecisionEngine,
    DecisionContext,
    DecisionResult,
    GateController,
    get_gate_controller,
)
from app.cv.gallery import FaceGallery, GalleryEntry
from app.cv.pipeline import Deduplicator, GateVisionPipeline
from app.cv.types import BoundingBox, RawFrame, VisionResult

__all__ = [
    "AccessDecisionEngine",
    "BoundingBox",
    "DecisionContext",
    "DecisionResult",
    "Deduplicator",
    "FaceGallery",
    "GalleryEntry",
    "GateController",
    "GateVisionPipeline",
    "RawFrame",
    "VisionEngine",
    "VisionResult",
    "get_gate_controller",
    "get_vision_engine",
]
