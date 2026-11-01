"""Vision engine factory: assembles detectors/readers into a pipeline."""

from __future__ import annotations

import threading
from typing import Any

import numpy as np

from app.core.config import Settings, get_settings
from app.core.exceptions import VisionEngineError
from app.core.logging import get_logger
from app.cv.detectors.insightface_face import InsightFaceDetector
from app.cv.detectors.mock import MockFaceDetector, MockPlateDetector
from app.cv.detectors.yolo_plate import YOLOPlateDetector
from app.cv.gallery import FaceGallery
from app.cv.pipeline import GateVisionPipeline
from app.cv.recognizers.easyocr_plate import EasyOCRPlateReader
from app.cv.recognizers.mock import MockPlateReader
from app.cv.recognizers.paddle_plate import PaddleOCRPlateReader
from app.cv.snapshots import SnapshotStore
from app.cv.types import Image, RawFrame, VisionOptions, VisionResult
from app.cv.utils import image_embedding

logger = get_logger(__name__)


class VisionEngine:
    """Owns the CV pipeline and guarantees thread-safe inference.

    Heavy models are loaded lazily and exactly once. In ``mock`` mode the engine
    is always ready and produces deterministic results for the offline demo.
    """

    def __init__(self, config: Settings | None = None) -> None:
        self.config = config or get_settings()
        self.mode = self.config.CV_MODE
        self._pipeline: GateVisionPipeline | None = None
        self._build_lock = threading.RLock()
        self._inference_lock = threading.Lock()
        self._warm_lock = threading.Lock()
        self._warmed = False
        self._ready = False
        self._warnings: list[str] = []
        if self.mode == "mock":
            self._warnings.append(
                "Mock vision engine active: detections are simulated for the offline demo "
                "(set CV_MODE=real to use YOLO + OCR + InsightFace)."
            )
        self._models_loaded: list[str] = []
        self._load_error: str | None = None
        self._mock_face: MockFaceDetector | None = None
        self._face_detector: Any = None

    # ------------------------------------------------------------------ build
    def _build_pipeline(self) -> GateVisionPipeline:
        with self._build_lock:
            if self._pipeline is not None:
                return self._pipeline
            if self.mode == "mock":
                self._warnings.append(
                    "Mock vision engine active: detections are simulated for the offline demo "
                    "(set CV_MODE=real to use YOLO + OCR + InsightFace)."
                )
                plate_detector: Any = MockPlateDetector()
                plate_reader: Any = MockPlateReader()
                face_detector: Any = MockFaceDetector()
            else:
                plate_detector = self._build_plate_detector()
                plate_reader = self._build_plate_reader()
                face_detector = self._build_face_detector()
            self._face_detector = face_detector
            if isinstance(face_detector, MockFaceDetector):
                self._mock_face = face_detector
            self._pipeline = GateVisionPipeline(
                plate_detector=plate_detector,
                plate_reader=plate_reader,
                face_detector=face_detector,
                snapshots=SnapshotStore(),
            )
            return self._pipeline

    def _build_plate_detector(self) -> Any:
        engine = (self.config.CV_PLATE_DETECTOR or "yolo").lower()
        if engine == "mock":
            self._warnings.append("Plate detector explicitly set to mock")
            return MockPlateDetector()
        return YOLOPlateDetector()

    def _build_plate_reader(self) -> Any:
        engine = (self.config.CV_OCR_ENGINE or "easyocr").lower()
        if engine == "mock":
            self._warnings.append("OCR engine explicitly set to mock")
            return MockPlateReader()
        if engine == "paddleocr":
            return PaddleOCRPlateReader(languages=self.config.CV_OCR_LANGUAGES)
        return EasyOCRPlateReader(languages=self.config.CV_OCR_LANGUAGES)

    def _build_face_detector(self) -> Any:
        engine = (self.config.CV_FACE_ENGINE or "insightface").lower()
        if engine == "mock":
            self._warnings.append("Face engine explicitly set to mock")
            return MockFaceDetector()
        return InsightFaceDetector(model_name=self.config.CV_FACE_MODEL_NAME)

    # ---------------------------------------------------------------- warmup
    def warmup(self, *, force: bool = False) -> bool:
        """Load every model and run a dummy inference. Returns readiness."""
        with self._warm_lock:
            if self._warmed and not force:
                return self._ready
            self._warmed = True
            if self.mode == "mock":
                self._ready = True
                self._models_loaded = ["mock-plate-detector", "mock-ocr", "mock-face-detector"]
                return self._ready
            pipeline = self._build_pipeline()
            errors: list[str] = []
            for label, component in (
                ("plate_detector", pipeline.plate_detector),
                ("plate_reader", pipeline.plate_reader),
                ("face_detector", pipeline.face_detector),
            ):
                load = getattr(component, "load", None)
                if callable(load):
                    try:
                        load()
                        self._models_loaded.append(getattr(component, "name", label))
                    except Exception as exc:
                        errors.append(f"{label}: {exc}")
                else:
                    self._models_loaded.append(getattr(component, "name", label))
            if errors:
                self._ready = False
                self._load_error = "; ".join(errors)
                for error in errors:
                    if error not in self._warnings:
                        self._warnings.append(error)
                logger.error("Vision engine not ready: %s", self._load_error)
                return False
            try:
                self.process(
                    RawFrame(
                        image=np.zeros((480, 640, 3), dtype=np.uint8),
                        camera_id=None,
                        gate_id=None,
                        source_id="warmup",
                        captured_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
                    ),
                    gallery=FaceGallery(),
                    annotate=False,
                )
            except Exception as exc:  # pragma: no cover - inference warmup issues
                logger.warning("Warmup inference failed: %s", exc)
            self._ready = True
            logger.info("Vision engine ready (models=%s)", ", ".join(self._models_loaded))
            return True

    async def warmup_async(self) -> bool:
        """Run :meth:`warmup` in a worker thread to keep the event loop free."""
        import asyncio

        return await asyncio.to_thread(self.warmup)

    # -------------------------------------------------------------- inference
    def process(
        self,
        frame: RawFrame,
        gallery: FaceGallery | None = None,
        *,
        annotate: bool = True,
        include_face: bool = True,
        options: VisionOptions | None = None,
    ) -> VisionResult:
        """Run the pipeline under the global inference lock."""
        if self.mode == "real" and self._warmed and not self._ready:
            raise VisionEngineError(
                self._load_error or "Vision models are not available. Check the CV configuration."
            )
        pipeline = self._build_pipeline()
        with self._inference_lock:
            return pipeline.process(
                frame,
                gallery=gallery,
                annotate=annotate,
                include_face=include_face,
                options=options,
            )

    def analyze_image(
        self,
        image: Image,
        gallery: FaceGallery | None = None,
        meta: dict[str, object] | None = None,
        options: VisionOptions | None = None,
    ) -> VisionResult:
        """Analyse an uploaded image (used by the manual verification endpoint)."""
        import datetime as dt

        frame = RawFrame(
            image=image,
            camera_id=None,
            gate_id=None,
            source_id="upload",
            captured_at=dt.datetime.now(dt.UTC),
            meta=dict(meta or {}),
        )
        return self.process(frame, gallery=gallery, options=options)

    def face_boxes(self, image: Image) -> list[Any]:
        """Detect every face in an image (used by enrollment quality checks)."""
        if self.mode == "mock":
            height, width = image.shape[:2]
            side = int(min(height, width) * 0.45)
            cx, cy = width // 2, height // 2
            from app.cv.types import BoundingBox

            return [
                BoundingBox(
                    max(0, cx - side // 2),
                    max(0, cy - side // 2),
                    min(width, cx + side // 2),
                    min(height, cy + side // 2),
                )
            ]
        pipeline = self._build_pipeline()
        detector = pipeline.face_detector
        detect = getattr(detector, "detect", None)
        if not callable(detect):
            return []
        with self._inference_lock:
            faces = detect(image)
        return [face.bbox for face in faces]

    def embedding_for_enrollment(self, image: Image) -> tuple[float, ...] | None:
        """Extract an embedding for face enrollment using the active engine."""
        if self.mode == "mock":
            crop = image
            return image_embedding(crop)
        detector = self._build_pipeline().face_detector
        embed = getattr(detector, "embed", None)
        if not callable(embed):
            raise VisionEngineError("Active face engine does not support enrollment")
        with self._inference_lock:
            embedding = embed(image)
        if embedding is None:
            return None
        return tuple(embedding)

    # ----------------------------------------------------------------- status
    def status(self) -> dict[str, Any]:
        """Return a serialisable status snapshot."""
        pipeline = self._pipeline
        return {
            "mode": self.mode,
            "plate_detector": getattr(getattr(pipeline, "plate_detector", None), "name", self.config.CV_PLATE_DETECTOR),
            "ocr_engine": getattr(getattr(pipeline, "plate_reader", None), "name", self.config.CV_OCR_ENGINE),
            "face_engine": getattr(getattr(pipeline, "face_detector", None), "name", self.config.CV_FACE_ENGINE),
            "engine_ready": self._ready or self.mode == "mock",
            "models_loaded": list(self._models_loaded),
            "warnings": list(self._warnings),
            "face_gallery_size": 0,
            "similarity_threshold": self.config.CV_FACE_SIMILARITY_THRESHOLD,
            "plate_confidence_threshold": self.config.CV_PLATE_CONFIDENCE_THRESHOLD,
            "ocr_min_confidence": self.config.CV_OCR_MIN_CONFIDENCE,
            "lazy_imports": True,
        }


_engine: VisionEngine | None = None
_engine_lock = threading.Lock()


def get_vision_engine() -> VisionEngine:
    """Return the process-wide vision engine singleton."""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = VisionEngine()
    return _engine


def reset_vision_engine() -> None:
    """Dispose the singleton (used by tests)."""
    global _engine
    with _engine_lock:
        _engine = None
