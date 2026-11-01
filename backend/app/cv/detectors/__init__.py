"""Plate and face detectors."""

from app.cv.detectors.mock import MockFaceDetector, MockPlateDetector
from app.cv.detectors.yolo_plate import YOLOPlateDetector

__all__ = ["MockFaceDetector", "MockPlateDetector", "YOLOPlateDetector"]
