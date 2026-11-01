"""InsightFace (RetinaFace + ArcFace) face detection and embedding extractor."""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.core.exceptions import VisionEngineError
from app.core.logging import get_logger
from app.cv.types import BoundingBox, FaceDetection, Image
from app.cv.utils import normalize_embedding

logger = get_logger(__name__)


class InsightFaceDetector:
    """Thin, defensive wrapper around ``insightface.app.FaceAnalysis``.

    Produces 512-dimensional *normalised* ArcFace embeddings that are compared
    with cosine similarity against the enrolled gallery.
    """

    name = "insightface"

    def __init__(
        self,
        model_name: str | None = None,
        det_size: int | None = None,
        min_face_size: int = 40,
        use_gpu: bool = False,
    ) -> None:
        self.model_name = model_name or settings.CV_FACE_MODEL_NAME
        self.det_size = det_size or settings.CV_FACE_DET_SIZE
        self.min_face_size = min_face_size
        self.use_gpu = use_gpu
        self._app: Any | None = None
        self._load_error: str | None = None

    @property
    def load_error(self) -> str | None:
        return self._load_error

    def load(self) -> None:
        """Initialise the InsightFace analysis pipeline."""
        if self._app is not None:
            return
        if self._load_error:
            raise VisionEngineError(self._load_error)
        try:
            from insightface.app import FaceAnalysis

            providers = (
                ["CUDAExecutionProvider", "CPUExecutionProvider"]
                if self.use_gpu
                else ["CPUExecutionProvider"]
            )
            app = FaceAnalysis(name=self.model_name, providers=providers, allowed_modules=["detection", "recognition"])
            app.prepare(ctx_id=0 if self.use_gpu else -1, det_size=(self.det_size, self.det_size))
            self._app = app
        except ImportError as exc:  # pragma: no cover - dependency guard
            self._load_error = (
                "insightface is not installed. Install the CV extras: "
                "pip install -r requirements-cv.txt (and ensure onnxruntime is available)."
            )
            raise VisionEngineError(self._load_error) from exc
        except Exception as exc:  # pragma: no cover - model download/runtime failure
            self._load_error = f"Failed to initialise InsightFace ({self.model_name}): {exc}"
            raise VisionEngineError(self._load_error) from exc
        logger.info("InsightFace detector ready (model=%s)", self.model_name)

    def detect(self, image: Image) -> list[FaceDetection]:
        self.load()
        assert self._app is not None
        try:
            faces = self._app.get(image)
        except Exception as exc:  # pragma: no cover - inference failure
            logger.error("InsightFace inference failed: %s", exc)
            return []

        detections: list[FaceDetection] = []
        for face in faces:
            coords = face.bbox.astype(int).tolist()
            bbox = BoundingBox(int(coords[0]), int(coords[1]), int(coords[2]), int(coords[3])).clamp(
                image
            )
            if bbox.width < self.min_face_size or bbox.height < self.min_face_size:
                continue
            raw_embedding = getattr(face, "normed_embedding", None)
            embedding = (
                normalize_embedding([float(v) for v in raw_embedding])
                if raw_embedding is not None
                else None
            )
            detections.append(
                FaceDetection(bbox=bbox, det_score=float(face.det_score), embedding=embedding)
            )
        detections.sort(key=lambda item: item.det_score, reverse=True)
        return detections

    def embed(self, image: Image, bbox: BoundingBox | None = None) -> tuple[float, ...] | None:
        """Extract the embedding of the most prominent face in an image."""
        faces = self.detect(image)
        if not faces:
            return None
        if bbox is not None:
            center_x, center_y = bbox.center
            faces.sort(
                key=lambda face: (face.bbox.center[0] - center_x) ** 2
                + (face.bbox.center[1] - center_y) ** 2
            )
        return faces[0].embedding

    def warmup(self) -> None:
        import numpy as np

        self.detect(np.zeros((640, 640, 3), dtype=np.uint8))
