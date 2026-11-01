"""Egyptian plate model support: class-name mapping, ONNX decoding, fetch script.

These tests are pure-python: no torch, no ultralytics, no network. They pin the
behaviour that lets one detector implementation serve every model shape we
document (Ultralytics ``.pt`` and exported YOLOv5/v7 ONNX), so a regression shows
up in CI instead of in front of a compound owner.
"""

from __future__ import annotations

import importlib.util
import pickle
import zipfile
from pathlib import Path

import numpy as np
import pytest

from app.core.exceptions import VisionEngineError
from app.cv.detectors.onnx_plate import ONNXPlateDetector, decode_yolo_output
from app.cv.detectors.yolo_plate import normalise_class_name

REPO_ROOT = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------- #
# Class-name normalisation (YOLO .pt path)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("License Plate", "license_plate"),
        ("license-plate", "license_plate"),
        ("LICENSE_PLATE", "license_plate"),
        ("  Number  Plate  ", "number_plate"),
        ("لوحة سيارة", "لوحة_سيارة"),
        ("Vehicle", "vehicle"),
        ("", ""),
    ],
)
def test_normalise_class_name(raw: str, expected: str) -> None:
    assert normalise_class_name(raw) == expected


def test_normalise_class_name_handles_none() -> None:
    # Ultralytics ``names`` can be a dict-like with missing entries.
    assert normalise_class_name(None) == ""


# --------------------------------------------------------------------------- #
# ONNX decoder (YOLOv5/v7 and YOLOv8 output layouts)
# --------------------------------------------------------------------------- #
def _yolov5_output(rows: list[list[float]], anchors: int | None = None) -> np.ndarray:
    """Build a YOLOv5-style ``[1, N, 5 + nc]`` tensor."""
    count = anchors or len(rows)
    width = len(rows[0])
    out = np.zeros((1, count, width), dtype=np.float32)
    for index, row in enumerate(rows):
        out[0, index] = row
    return out


def _yolov8_output(columns: list[list[float]], anchors: int | None = None) -> np.ndarray:
    """Build a YOLOv8-style ``[1, 4 + nc, N]`` tensor."""
    count = anchors or len(columns)
    attributes = len(columns[0])
    out = np.zeros((1, attributes, count), dtype=np.float32)
    for index, column in enumerate(columns):
        out[0, :, index] = column
    return out


def test_yolov5_layout_objectness_multiplies_class_score() -> None:
    output = _yolov5_output(
        [[320.0, 240.0, 100.0, 40.0, 0.9, 0.8]],
        anchors=25200,
    )
    boxes, scores = decode_yolo_output(output, confidence=0.25, class_filter={0})
    assert boxes == [[320.0, 240.0, 100.0, 40.0]]
    assert scores[0] == pytest.approx(0.72, abs=1e-5)


def test_yolov5_layout_drops_low_confidence_rows() -> None:
    output = _yolov5_output(
        [[10.0, 10.0, 20.0, 20.0, 0.10, 0.10]],  # 0.01 after multiplication
        anchors=25200,
    )
    assert decode_yolo_output(output, confidence=0.25, class_filter={0}) == ([], [])


def test_yolov8_layout_single_class_score() -> None:
    output = _yolov8_output(
        [[320.0, 240.0, 100.0, 40.0, 0.88]],
        anchors=8400,
    )
    boxes, scores = decode_yolo_output(output, confidence=0.25, class_filter={0})
    assert boxes == [[320.0, 240.0, 100.0, 40.0]]
    assert scores[0] == pytest.approx(0.88, abs=1e-5)


def test_yolov8_layout_with_multiple_classes_uses_class_filter() -> None:
    # Anchor 0: plate 0.75 / vehicle 0.10.  Anchor 1: plate 0.40 / vehicle 0.95.
    anchor0 = [100.0, 100.0, 40.0, 20.0, 0.75, 0.10]
    anchor1 = [500.0, 100.0, 40.0, 20.0, 0.40, 0.95]
    output = _yolov8_output([anchor0, anchor1], anchors=8400)

    # The filter selects the best *allowed* class, so anchor 1 reports the plate
    # score (0.40) even though `vehicle` scored higher.
    boxes, scores = decode_yolo_output(output, confidence=0.25, class_filter={0})
    assert boxes == [[100.0, 100.0, 40.0, 20.0], [500.0, 100.0, 40.0, 20.0]]
    assert scores == pytest.approx([0.75, 0.40], abs=1e-5)

    # No filter keeps the highest-scoring class per anchor.
    _, unfiltered = decode_yolo_output(output, confidence=0.25, class_filter=None)
    assert unfiltered == pytest.approx([0.75, 0.95], abs=1e-5)

    # A model with no plate class at all falls back to "keep everything".
    boxes, scores = decode_yolo_output(output, confidence=0.25, class_filter={7})
    assert boxes == []


def test_decode_returns_raw_boxes_and_leaves_nms_to_the_detector() -> None:
    # cv2.dnn.NMSBoxes runs inside ONNXPlateDetector.detect (needs OpenCV + a
    # loaded net), so the pure decoder must not silently drop duplicates.
    output = _yolov8_output(
        [
            [100.0, 100.0, 40.0, 20.0, 0.90],
            [102.0, 101.0, 40.0, 20.0, 0.85],
        ],
        anchors=8400,
    )
    boxes, scores = decode_yolo_output(output, confidence=0.25, class_filter={0})
    assert len(boxes) == 2
    assert scores == pytest.approx([0.90, 0.85], abs=1e-5)


def test_decode_rejects_unknown_layout() -> None:
    with pytest.raises(VisionEngineError):
        decode_yolo_output(np.zeros((3, 4, 5, 6), dtype=np.float32), confidence=0.3)


# --------------------------------------------------------------------------- #
# Fetch script
# --------------------------------------------------------------------------- #
def _load_fetcher():
    """Import scripts/fetch_plate_model.py as a module (dataclasses need sys.modules)."""
    import sys

    name = "fetch_plate_model_under_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / "fetch_plate_model.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _fake_checkpoint(path: Path, *, class_names: tuple[str, ...] = ("License Plate",)) -> Path:
    """Write a minimal torch-style ZIP that the verifier can inspect."""
    payload = pickle.dumps(
        {
            "model": "ultralytics.nn.tasks.DetectionModel",
            "task": "detect",
            "names": list(class_names),
        },
        protocol=4,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("best/data.pkl", payload)
        archive.writestr("best/version", b"3\n")
    return path


def test_fetch_script_lists_both_egyptian_models() -> None:
    fetcher = _load_fetcher()
    assert set(fetcher.SOURCES) == {"egy-v8m", "egy-v8s"}
    for source in fetcher.SOURCES.values():
        assert source.sha256 and len(source.sha256) == 64
        assert source.path.endswith(".pt")
        assert source.repo.count("/") == 1


def test_fetch_script_verifies_a_plate_checkpoint(tmp_path: Path) -> None:
    fetcher = _load_fetcher()
    checkpoint = _fake_checkpoint(tmp_path / "plate_yolov8.pt")
    report = fetcher.verify_file(checkpoint, expected_sha256=None, check_checksum=False)
    assert report["is_ultralytics"] is True
    assert report["is_detection_model"] is True
    assert report["looks_like_plate_model"] is True
    assert "License Plate" in report["class_names"]


def test_fetch_script_rejects_non_plate_checkpoint(tmp_path: Path) -> None:
    fetcher = _load_fetcher()
    checkpoint = _fake_checkpoint(tmp_path / "face.pt", class_names=("person", "car"))
    with pytest.raises(fetcher.FetchError, match="plate"):
        fetcher.verify_file(checkpoint, expected_sha256=None, check_checksum=False)


def test_fetch_script_rejects_html_error_page(tmp_path: Path) -> None:
    fetcher = _load_fetcher()
    bogus = tmp_path / "plate_yolov8.pt"
    bogus.write_bytes(b"<!DOCTYPE html><html>404</html>")
    with pytest.raises(fetcher.FetchError, match="ZIP"):
        fetcher.verify_file(bogus, expected_sha256=None, check_checksum=False)


def test_fetch_script_checksum_mismatch_is_fatal(tmp_path: Path) -> None:
    fetcher = _load_fetcher()
    checkpoint = _fake_checkpoint(tmp_path / "plate_yolov8.pt")
    with pytest.raises(fetcher.FetchError, match="sha256 mismatch"):
        fetcher.verify_file(checkpoint, expected_sha256="0" * 64)


def test_fetch_script_destination_defaults_to_backend_models(monkeypatch: pytest.MonkeyPatch) -> None:
    fetcher = _load_fetcher()
    monkeypatch.delenv("CV_PLATE_MODEL_PATH", raising=False)
    assert fetcher._default_destination() == REPO_ROOT / "backend" / "models" / "plate_yolov8.pt"

    # A container path is mapped back to the mounted host directory.
    monkeypatch.setenv("CV_PLATE_MODEL_PATH", "/app/models/plate_yolov8.pt")
    assert fetcher._default_destination() == REPO_ROOT / "backend" / "models" / "plate_yolov8.pt"


def test_fetch_script_container_hint_matches_compose_mount() -> None:
    fetcher = _load_fetcher()
    host = REPO_ROOT / "backend" / "models" / "plate_yolov8.pt"
    assert fetcher._container_hint(host) == "/app/models/plate_yolov8.pt"
    assert fetcher._container_hint(Path("/opt/weights/x.pt")) == "/opt/weights/x.pt"


# --------------------------------------------------------------------------- #
# Engine wiring: CV_PLATE_DETECTOR selects the detector implementation
# --------------------------------------------------------------------------- #
class _EngineConfig:
    """Minimal Settings stand-in — VisionEngine only reads these attributes."""

    CV_MODE = "real"
    CV_PLATE_DETECTOR = "yolo"
    CV_OCR_ENGINE = "easyocr"
    CV_FACE_ENGINE = "insightface"
    CV_FACE_SIMILARITY_THRESHOLD = 0.45
    CV_PLATE_CONFIDENCE_THRESHOLD = 0.35
    CV_OCR_MIN_CONFIDENCE = 0.45


def _engine_with(detector: str):
    from app.cv.engine import VisionEngine

    class _Config(_EngineConfig):
        CV_PLATE_DETECTOR = detector

    return VisionEngine(_Config())  # type: ignore[arg-type]


@pytest.mark.parametrize("engine_name", ["yolo", "YOLO", ""])
def test_engine_defaults_to_the_ultralytics_detector(engine_name: str) -> None:
    from app.cv.detectors.yolo_plate import YOLOPlateDetector

    assert isinstance(_engine_with(engine_name)._build_plate_detector(), YOLOPlateDetector)  # noqa: SLF001


@pytest.mark.parametrize("engine_name", ["onnx", "ONNX", "openvino", "cv2"])
def test_engine_builds_the_onnx_detector_when_requested(engine_name: str) -> None:
    detector = _engine_with(engine_name)._build_plate_detector()  # noqa: SLF001
    assert isinstance(detector, ONNXPlateDetector)
    assert detector.name == "onnx-plate-detector"


def test_engine_mock_detector_only_on_explicit_opt_in() -> None:
    from app.cv.detectors.mock import MockPlateDetector

    engine = _engine_with("mock")
    assert isinstance(engine._build_plate_detector(), MockPlateDetector)  # noqa: SLF001
    assert any("mock" in warning.lower() for warning in engine.status()["warnings"])


def _real_settings(**overrides):
    """A real-mode Settings copy (env vars win over init kwargs, so copy instead)."""
    from app.core.config import Settings

    return Settings().model_copy(update={"CV_MODE": "real", **overrides})


def test_config_warns_about_an_unknown_plate_engine() -> None:
    warnings = _real_settings(CV_PLATE_DETECTOR="yolov9").cv_warnings()
    assert any("CV_PLATE_DETECTOR" in warning for warning in warnings)

    assert not any(
        "CV_PLATE_DETECTOR" in warning
        for warning in _real_settings(CV_PLATE_DETECTOR="onnx").cv_warnings()
    )
