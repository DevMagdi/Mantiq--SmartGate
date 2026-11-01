"""ONNX license-plate detector (architecture agnostic).

Ultralytics ``.pt`` checkpoints cover YOLOv8/YOLO11 and are handled by
:class:`app.cv.detectors.yolo_plate.YOLOPlateDetector`. Many Egyptian plate
models published on GitHub are **YOLOv5** or **YOLOv7** checkpoints, which the
Ultralytics loader cannot open. Exporting those to ONNX and running them through
OpenCV's DNN module gives a dependency-free path that works everywhere the app
already runs (OpenCV is a hard requirement), including CPU-only edge boxes.

Usage::

    yolo export model=car_plate_detector.pt format=onnx opset=12   # YOLOv5
    python export.py --weights car_plate_detector.pt --include onnx # YOLOv7
    CV_PLATE_DETECTOR=onnx
    CV_PLATE_MODEL_PATH=models/plate_egy_v5.onnx

The decoder understands both common output layouts:

* ``[1, N, 5 + nc]``  — YOLOv5 / YOLOv7 (``x, y, w, h, objectness, classes…``)
* ``[1, 4 + nc, N]``  — YOLOv8 / YOLO11 exports (``cx, cy, w, h, classes…``)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from app.core.config import settings
from app.core.exceptions import VisionEngineError
from app.core.logging import get_logger
from app.cv.detectors.yolo_plate import normalise_class_name
from app.cv.types import BoundingBox, Image, PlateDetection

logger = get_logger(__name__)


class ONNXPlateDetector:
    """Runs an exported YOLO plate detector with ``cv2.dnn``."""

    name = "onnx-plate-detector"

    def __init__(
        self,
        model_path: str | None = None,
        confidence: float | None = None,
        iou: float | None = None,
        image_size: int | None = None,
        max_detections: int = 5,
        class_names: list[str] | None = None,
    ) -> None:
        self.model_path = Path(model_path or settings.CV_PLATE_MODEL_PATH)
        self.confidence = (
            settings.CV_PLATE_CONFIDENCE_THRESHOLD if confidence is None else confidence
        )
        self.iou = settings.CV_YOLO_IOU if iou is None else iou
        self.image_size = settings.CV_YOLO_IMAGE_SIZE if image_size is None else image_size
        self.max_detections = max_detections
        self._class_names = list(class_names or ["plate"])
        self._net: Any | None = None
        self._load_error: str | None = None
        self._input_size: tuple[int, int] | None = None

    # ------------------------------------------------------------------ loading
    @property
    def load_error(self) -> str | None:
        return self._load_error

    @property
    def is_available(self) -> bool:
        return self.model_path.exists()

    def load(self) -> None:
        """Read the ONNX graph (lazy: a missing file never blocks booting)."""
        if self._net is not None:
            return
        if self._load_error:
            raise VisionEngineError(self._load_error)
        if not self.model_path.exists():
            self._load_error = (
                f"ONNX plate model not found at '{self.model_path}'. Export a YOLOv5/YOLOv7 "
                "plate detector with `yolo export model=best.pt format=onnx opset=12`, "
                "then set CV_PLATE_MODEL_PATH (see docs/real-deployment.md §3.2)."
            )
            raise VisionEngineError(self._load_error)
        try:
            import cv2
        except ImportError as exc:  # pragma: no cover - OpenCV is a hard dependency
            raise VisionEngineError("OpenCV (cv2) is required for the ONNX detector") from exc
        try:
            self._net = cv2.dnn.readNetFromONNX(str(self.model_path))
        except Exception as exc:  # pragma: no cover - model specific
            self._load_error = f"Failed to load ONNX plate model: {exc}"
            raise VisionEngineError(self._load_error) from exc
        logger.info("ONNX plate detector loaded from %s", self.model_path)

    def warmup(self) -> None:
        """Run a dummy inference so the first real frame is fast."""
        self.detect(np.zeros((480, 640, 3), dtype=np.uint8))

    # ---------------------------------------------------------------- inference
    def detect(self, image: Image) -> list[PlateDetection]:
        self.load()
        import cv2

        height, width = image.shape[:2]
        if height == 0 or width == 0:
            return []
        size = self._input_size or (self.image_size, self.image_size)
        scale = min(size[0] / width, size[1] / height)
        new_w, new_h = int(round(width * scale)), int(round(height * scale))
        pad_w, pad_h = (size[0] - new_w) / 2, (size[1] - new_h) / 2
        canvas = np.full((size[1], size[0], 3), 114, dtype=np.uint8)
        resized = cv2.resize(image, (new_w, new_h))
        top, left = int(round(pad_h - 0.1)), int(round(pad_w - 0.1))
        canvas[top : top + new_h, left : left + new_w] = resized

        blob = cv2.dnn.blobFromImage(
            canvas, scalefactor=1 / 255.0, size=size, swapRB=True, crop=False
        )
        self._net.setInput(blob)
        output = self._net.forward()
        boxes, scores = decode_yolo_output(
            output, confidence=self.confidence, class_filter=self._plate_class_ids()
        )
        if not boxes:
            return []

        # Map letterboxed coordinates back to the original frame.
        mapped = [
            (
                [(x - pad_w) / scale, (y - pad_h) / scale, (w / scale), (h / scale)],
                score,
            )
            for (x, y, w, h), score in zip(boxes, scores)
        ]
        indices = cv2.dnn.NMSBoxes(
            [box for box, _ in mapped],
            [float(score) for _, score in mapped],
            self.confidence,
            self.iou,
        )
        detections: list[PlateDetection] = []
        for index in np.array(indices).flatten()[: self.max_detections]:
            (cx, cy, w, h), score = mapped[int(index)]
            bbox = BoundingBox(
                int(cx - w / 2), int(cy - h / 2), int(cx + w / 2), int(cy + h / 2)
            ).clamp(image)
            if bbox.width < 20 or bbox.height < 8:
                continue
            detections.append(PlateDetection(bbox=bbox, confidence=float(score), label="plate"))
        detections.sort(key=lambda item: item.confidence, reverse=True)
        return detections[: self.max_detections]

    # ----------------------------------------------------------------- helpers
    def _plate_class_ids(self) -> set[int] | None:
        wanted = {
            normalise_class_name(token)
            for token in (settings.CV_PLATE_CLASS_NAMES or "").split(",")
            if token.strip()
        }
        if not wanted:
            return None
        matched = {
            index
            for index, label in enumerate(self._class_names)
            if normalise_class_name(label) in wanted
        }
        return matched or None


def decode_yolo_output(
    output: Any,
    *,
    confidence: float,
    class_filter: set[int] | None = None,
) -> tuple[list[list[float]], list[float]]:
    """Decode a raw YOLO head into ``(cx, cy, w, h)`` boxes and scores.

    Two layouts are supported and told apart by shape (not by guessing per row):

    * YOLOv5 / YOLOv7 — ``[1, N, 5 + nc]``: ``cx, cy, w, h, objectness, classes…``
    * YOLOv8 / YOLO11 — ``[1, 4 + nc, N]``: ``cx, cy, w, h, classes…``

    Kept as a pure function so the matrix handling is unit-tested without an
    ONNX runtime installed.
    """
    predictions = np.asarray(output, dtype=np.float32)
    if predictions.ndim == 3:
        predictions = predictions[0]
    if predictions.ndim != 2:
        raise VisionEngineError(f"Unexpected YOLO output shape: {predictions.shape}")
    if predictions.shape[0] == 0 or predictions.shape[1] == 0:
        return [], []

    # YOLOv8 exports attributes first ([4+nc, N]); YOLOv5 exports anchors first.
    yolo_v8_layout = predictions.shape[0] < predictions.shape[1]
    if yolo_v8_layout:
        predictions = predictions.T

    attributes = predictions.shape[1]
    if attributes < 5:
        return [], []

    boxes: list[list[float]] = []
    scores: list[float] = []
    for row in predictions:
        cx, cy, width, height = (float(value) for value in row[:4])
        if width <= 0 or height <= 0:
            continue
        if yolo_v8_layout:
            class_scores = row[4:]
            objectness = 1.0
        else:
            class_scores = row[5:]
            objectness = float(row[4])
        if not class_scores.size:
            # Objectness-only head (rare): treat the row as a single plate class.
            if class_filter is not None and 0 not in class_filter:
                continue
            score = objectness
        else:
            # A multi-class model (plate + vehicle) must still report a plate:
            # restrict the argmax to the allowed classes instead of dropping the
            # row just because another class scored higher.
            allowed = (
                np.array(sorted(index for index in class_filter if index < class_scores.size))
                if class_filter is not None
                else None
            )
            if allowed is not None and allowed.size == 0:
                continue
            candidates = class_scores if allowed is None else class_scores[allowed]
            score = float(candidates[int(np.argmax(candidates))]) * objectness
        if score < confidence:
            continue
        boxes.append([cx, cy, width, height])
        scores.append(score)
    return boxes, scores


__all__ = ["ONNXPlateDetector", "decode_yolo_output"]
