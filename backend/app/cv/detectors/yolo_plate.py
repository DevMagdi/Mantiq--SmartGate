"""YOLO (Ultralytics) license plate detector."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.exceptions import VisionEngineError
from app.core.logging import get_logger
from app.cv.types import BoundingBox, Image, PlateDetection

logger = get_logger(__name__)


def normalise_class_name(name: object) -> str:
    """Normalise a model class label for matching.

    Egyptian plate models in the wild use ``License Plate``, ``license-plate``,
    ``plate`` or ``رقم_اللوحة``; all of them must map to the same token so the
    dashboards and the class filter behave the same regardless of the dataset.
    """
    if name is None:
        return ""
    return "_".join(str(name).strip().lower().replace("-", "_").split())


class YOLOPlateDetector:
    """Ultralytics YOLOv8/YOLOv10 wrapper trained for plate detection.

    The model is loaded lazily so that a missing weights file never prevents the
    API from booting: the pipeline simply reports itself as unavailable and the
    dashboard surfaces an actionable warning.
    """

    name = "yolo-plate-detector"

    def __init__(
        self,
        model_path: str | None = None,
        confidence: float | None = None,
        iou: float | None = None,
        image_size: int | None = None,
        max_detections: int = 5,
        device: str | None = None,
        half: bool | None = None,
    ) -> None:
        self.model_path = Path(model_path or settings.CV_PLATE_MODEL_PATH)
        self.confidence = (
            settings.CV_PLATE_CONFIDENCE_THRESHOLD if confidence is None else confidence
        )
        self.iou = settings.CV_YOLO_IOU if iou is None else iou
        self.image_size = settings.CV_YOLO_IMAGE_SIZE if image_size is None else image_size
        self.max_detections = max_detections
        # ``None`` lets Ultralytics pick the device (CUDA when available).
        self.device = device or (settings.CV_YOLO_DEVICE or None)
        self.half = settings.CV_YOLO_HALF if half is None else half
        self._model: Any | None = None
        self._load_error: str | None = None
        self._class_names: list[str] = []
        self._plate_class_ids: set[int] | None = None

    @property
    def load_error(self) -> str | None:
        return self._load_error

    def load(self) -> None:
        """Load the YOLO weights, raising a descriptive error on failure."""
        if self._model is not None:
            return
        if self._load_error:
            raise VisionEngineError(self._load_error)
        if not self.model_path.exists():
            self._load_error = (
                f"Plate detection model not found at '{self.model_path}'. "
                "Run `python3 scripts/fetch_plate_model.py` to download a verified "
                "Egyptian plate detector, or point CV_PLATE_MODEL_PATH at your own "
                "YOLOv8/YOLO11 weights (docs/real-deployment.md §3)."
            )
            raise VisionEngineError(self._load_error)
        try:
            from ultralytics import YOLO

            self._model = YOLO(str(self.model_path))
            names = getattr(self._model, "names", {}) or {}
            if isinstance(names, dict):
                self._class_names = [str(value) for value in names.values()]
            self._plate_class_ids = self._resolve_plate_classes()
            logger.info(
                "Plate model classes: %s",
                ", ".join(self._class_names) if self._class_names else "unnamed",
            )
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise VisionEngineError(
                "ultralytics is not installed. Install the CV extras: "
                "pip install -r requirements-cv.txt"
            ) from exc
        except Exception as exc:  # pragma: no cover - model specific
            self._load_error = f"Failed to load plate model: {exc}"
            raise VisionEngineError(self._load_error) from exc
        logger.info("YOLO plate detector loaded from %s", self.model_path)

    def _resolve_plate_classes(self) -> set[int] | None:
        """Return the class ids that represent a plate, or ``None`` for all.

        Multi-class models (COCO, traffic datasets) also detect cars, people and
        signs; keeping only the plate classes is what stops a "car" box from
        being sent to OCR. A single-class custom plate model has no matching
        name, so every detection is kept.
        """
        wanted = {
            normalise_class_name(token)
            for token in (settings.CV_PLATE_CLASS_NAMES or "").split(",")
            if token.strip()
        }
        if not wanted or not self._class_names:
            return None
        matched = {
            index
            for index, name in enumerate(self._class_names)
            if normalise_class_name(name) in wanted
        }
        if not matched:
            return None
        logger.info(
            "Plate detector will keep classes %s out of %s",
            sorted(self._class_names[index] for index in matched),
            len(self._class_names),
        )
        return matched

    def detect(self, image: Image) -> list[PlateDetection]:
        self.load()
        assert self._model is not None
        try:
            # ``half`` (fp16) only makes sense on a CUDA device; recent
            # Ultralytics releases also emit a deprecation warning when it is
            # passed as False on CPU, so only forward it when enabled.
            predict_kwargs: dict[str, Any] = {
                "conf": self.confidence,
                "iou": self.iou,
                "imgsz": self.image_size,
                "max_det": self.max_detections,
                "verbose": False,
                "device": self.device,
            }
            if self.half:
                predict_kwargs["half"] = True
            results = self._model.predict(image, **predict_kwargs)
        except Exception as exc:  # pragma: no cover - inference failure
            logger.error("YOLO inference failed: %s", exc)
            return []

        detections: list[PlateDetection] = []
        height, width = image.shape[:2]
        for result in results:
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                continue
            for box in boxes:
                coords = box.xyxy[0].tolist()
                score = float(box.conf[0])
                bbox = BoundingBox(
                    int(coords[0]), int(coords[1]), int(coords[2]), int(coords[3])
                ).clamp(image)
                if bbox.width < 20 or bbox.height < 8:
                    continue
                label: str | None = None
                cls_id = getattr(box, "cls", None)
                class_index: int | None = None
                if cls_id is not None:
                    try:
                        class_index = int(cls_id[0])
                    except (IndexError, TypeError, ValueError):
                        class_index = None
                if class_index is not None and self._class_names:
                    try:
                        label = self._class_names[class_index]
                    except IndexError:
                        label = None
                if (
                    class_index is not None
                    and self._plate_class_ids is not None
                    and class_index not in self._plate_class_ids
                ):
                    continue
                detections.append(
                    PlateDetection(bbox=bbox, confidence=score, label=label)
                )
        detections.sort(key=lambda item: item.confidence, reverse=True)
        return detections

    def warmup(self) -> None:
        """Run a single dummy inference so the first real frame is fast."""
        import numpy as np

        self.detect(np.zeros((640, 640, 3), dtype=np.uint8))

    @property
    def is_available(self) -> bool:
        return self.model_path.exists()
