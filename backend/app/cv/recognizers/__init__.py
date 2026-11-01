"""Plate OCR engines."""

from app.cv.recognizers.easyocr_plate import EasyOCRPlateReader
from app.cv.recognizers.mock import MockPlateReader
from app.cv.recognizers.paddle_plate import PaddleOCRPlateReader

__all__ = ["EasyOCRPlateReader", "MockPlateReader", "PaddleOCRPlateReader"]
