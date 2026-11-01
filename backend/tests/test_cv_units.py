"""Unit tests for pure CV helpers, the gallery and the pipeline orchestration."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence

import numpy as np
import pytest

from app.cv.gallery import FaceGallery, GalleryEntry
from app.cv.pipeline import GateVisionPipeline
from app.cv.snapshots import SnapshotStore
from app.cv.types import (
    BoundingBox,
    FaceDetection,
    PlateDetection,
    PlateReading,
    RawFrame,
)
from app.cv.utils import (
    blur_score,
    clean_plate_text,
    deterministic_embedding,
    format_plate,
    normalize_plate,
    plate_variants,
    valid_plate_candidate,
)


def test_plate_normalisation_and_formatting() -> None:
    assert clean_plate_text(" cai-4821 ") == "CAI4821"
    assert normalize_plate("cai 4821") == "CAI4821"
    assert normalize_plate(None) == ""
    assert format_plate("cai-4821") == "CAI 4821"
    assert format_plate("D K 1 2 3 4") == "DK 1234"
    assert format_plate("") == ""


def test_arabic_indic_digits_are_normalised() -> None:
    assert clean_plate_text("ق ١٢٣٤") == "ق1234"
    assert format_plate("ق ١٢٣٤") == "ق 1234"


def test_plate_variants_cover_ocr_confusions() -> None:
    variants = plate_variants("CAI 4821")
    assert "CAI4821" in variants
    # 1↔I and 5↔S confusions are both produced.
    assert "CA14821" in variants
    assert plate_variants(None) == set()


def test_plate_candidate_validation() -> None:
    assert valid_plate_candidate("CAI 4821")
    assert not valid_plate_candidate("AB")
    assert not valid_plate_candidate("ABCD")
    assert not valid_plate_candidate("1234")
    assert not valid_plate_candidate("")


def test_blur_score_orders_sharp_and_blurry_images() -> None:
    sharp = np.zeros((100, 100, 3), dtype=np.uint8)
    sharp[::4, :] = 255
    blurry = np.full((100, 100, 3), 128, dtype=np.uint8)
    assert blur_score(sharp) > blur_score(blurry)


def test_gallery_match_and_threshold() -> None:
    first, second = uuid.uuid4(), uuid.uuid4()
    gallery = FaceGallery(
        [
            GalleryEntry(resident_id=first, embedding=deterministic_embedding("a")),
            GalleryEntry(resident_id=second, embedding=deterministic_embedding("b")),
        ]
    )
    assert len(gallery) == 2
    match = gallery.match(deterministic_embedding("a"), threshold=0.4)
    assert match is not None and match.resident_id == first
    assert gallery.match(deterministic_embedding("unrelated"), threshold=0.99) is None
    assert gallery.match([], threshold=0.1) is None
    assert -1.0 <= gallery.similarity(
        deterministic_embedding("a"), deterministic_embedding("b")
    ) <= 1.0
    assert gallery.stats()["dimension"] == 512


def test_gallery_skips_invalid_vectors() -> None:
    gallery = FaceGallery(
        [
            GalleryEntry(resident_id=uuid.uuid4(), embedding=(0.0, 0.0)),
            GalleryEntry(resident_id=uuid.uuid4(), embedding=deterministic_embedding("valid")),
        ]
    )
    assert len(gallery) == 1


class _StaticPlateDetector:
    name = "static"

    def __init__(self, boxes: Sequence[tuple[BoundingBox, float]]) -> None:
        self._boxes = boxes

    def detect(self, image: np.ndarray) -> list[PlateDetection]:
        return [PlateDetection(bbox=box, confidence=conf) for box, conf in self._boxes]


class _StaticReader:
    name = "static-ocr"

    def __init__(self, readings: dict[str, tuple[str, float]]) -> None:
        self._readings = readings

    def read(self, image: np.ndarray, box: BoundingBox) -> PlateReading:
        key = f"{box.x1}-{box.y1}"
        text, confidence = self._readings[key]
        return PlateReading(text=text, confidence=confidence, bbox=box, engine=self.name)


class _StaticFaceDetector:
    name = "static-face"

    def __init__(self, embeddings: list[tuple[float, ...]]) -> None:
        self._embeddings = embeddings

    def detect(self, image: np.ndarray) -> list[FaceDetection]:
        return [
            FaceDetection(
                bbox=BoundingBox(10, 10, 90, 90),
                det_score=0.99,
                embedding=embedding,
            )
            for embedding in self._embeddings
        ]


def _frame() -> RawFrame:
    return RawFrame(
        image=np.zeros((240, 320, 3), dtype=np.uint8),
        camera_id=uuid.uuid4(),
        gate_id=uuid.uuid4(),
        source_id="unit-test",
        captured_at=datetime.now(UTC),
        meta={"plate_text": "CAI 4821"},
    )


def test_pipeline_selects_best_plate(tmp_path: Path) -> None:
    weak_box = BoundingBox(10, 150, 130, 190)
    strong_box = BoundingBox(150, 150, 300, 190)
    resident_id = uuid.uuid4()
    gallery = FaceGallery(
        [
            GalleryEntry(
                resident_id=resident_id,
                embedding=deterministic_embedding("resident:test"),
                embedding_id=uuid.uuid4(),
            )
        ]
    )
    pipeline = GateVisionPipeline(
        plate_detector=_StaticPlateDetector([(weak_box, 0.5), (strong_box, 0.95)]),
        plate_reader=_StaticReader(
            {"10-150": ("AA 1111", 0.55), "150-150": ("CAI 4821", 0.94)}
        ),
        face_detector=_StaticFaceDetector([deterministic_embedding("resident:test")]),
        snapshots=SnapshotStore(root=tmp_path, url_prefix="/media"),
        face_threshold=0.4,
    )
    result = pipeline.process(_frame(), gallery)
    assert result.plate is not None
    assert result.plate.text == "CAI4821"
    assert result.plate.confidence == pytest.approx(0.94)
    assert result.face_match is not None
    assert result.face_match.resident_id == resident_id
    assert result.plate_snapshot_url and result.plate_snapshot_url.startswith("/media/snapshots/")
    plate_crop = result.raw["plate_crop_url"]
    assert isinstance(plate_crop, str) and plate_crop.startswith("/media/plates/")
    assert result.face_snapshot_url and result.face_snapshot_url.startswith("/media/faces/")
    assert result.processing_ms >= 0
    saved = list((tmp_path / "plates").rglob("*.jpg"))
    assert saved


def test_pipeline_rejects_low_confidence_and_bad_aspect(tmp_path: Path) -> None:
    wide = BoundingBox(0, 0, 320, 20)  # aspect 16 -> rejected before OCR
    small = BoundingBox(100, 100, 180, 140)
    pipeline = GateVisionPipeline(
        plate_detector=_StaticPlateDetector([(wide, 0.9), (small, 0.9)]),
        plate_reader=_StaticReader({"100-100": ("CAI 4821", 0.2)}),
        face_detector=_StaticFaceDetector([]),
        snapshots=SnapshotStore(root=tmp_path),
    )
    result = pipeline.process(_frame())
    assert result.plate is None
    assert result.face is None

    empty = GateVisionPipeline(
        plate_detector=_StaticPlateDetector([]),
        plate_reader=_StaticReader({}),
        face_detector=_StaticFaceDetector([]),
        snapshots=SnapshotStore(root=tmp_path),
    )
    no_detection = empty.process(_frame())
    assert no_detection.plate is None and no_detection.face is None


def test_snapshot_store_writes_and_encodes(tmp_path: Path) -> None:
    store = SnapshotStore(root=tmp_path, url_prefix="/media")
    image = np.zeros((60, 120, 3), dtype=np.uint8)
    url = store.save_crop(image, BoundingBox(0, 0, 60, 30), kind="plates")
    assert url.startswith("/media/plates/")
    path = tmp_path / url[len("/media/") :]
    assert path.exists()
    encoded = store.encode_jpeg(image)
    assert encoded[:2] == b"\xff\xd8"
    assert store.save_bytes(b"\xff\xd8\xff\xe0bytes", extension="jpg").startswith("/media/faces/")
