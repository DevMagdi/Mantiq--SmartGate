"""Plate and face detectors."""

from app.cv.detectors.mock import MockFaceDetector, MockPlateDetector
from app.cv.detectors.onnx_plate import ONNXPlateDetector
from app.cv.detectors.yolo_plate import YOLOPlateDetector, normalise_class_name

__all__ = [
    "MockFaceDetector",
    "MockPlateDetector",
    "ONNXPlateDetector",
    "YOLOPlateDetector",
    "normalise_class_name",
]
