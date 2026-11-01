"""Frame sources: RTSP/USB/file cameras and a synthetic demo renderer."""

from __future__ import annotations

import math
import time
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

import cv2
import numpy as np

from app.core.config import settings
from app.core.exceptions import VisionEngineError
from app.core.logging import get_logger
from app.cv.demo_data import DEMO_SCENARIOS, DemoScenario
from app.cv.types import BoundingBox, Image

logger = get_logger(__name__)


class FrameSource(ABC):
    """A pull-based camera stream."""

    def __init__(self, source_url: str, name: str) -> None:
        self.source_url = source_url
        self.name = name
        self.last_meta: dict[str, Any] = {}

    @abstractmethod
    def open(self) -> None:
        """Open the underlying stream."""

    @abstractmethod
    def read(self) -> Image | None:
        """Return the next BGR frame or ``None`` on failure."""

    @abstractmethod
    def close(self) -> None:
        """Release the underlying stream."""

    def meta(self) -> dict[str, Any]:
        """Return metadata attached to the most recent frame."""
        return self.last_meta


class OpenCVFrameSource(FrameSource):
    """OpenCV backed source supporting RTSP, HTTP, USB indexes and video files."""

    RECONNECT_DELAY_SECONDS = 2.0

    def __init__(self, source_url: str, name: str, width: int | None = None) -> None:
        super().__init__(source_url, name)
        self.width = width or settings.CV_FRAME_WIDTH
        self._capture: cv2.VideoCapture | None = None
        self._is_file = False

    def _target(self) -> int | str:
        value = self.source_url.strip()
        if value.isdigit():
            return int(value)
        return value

    def open(self) -> None:
        if self._capture is not None:
            return
        target = self._target()
        self._is_file = isinstance(target, str) and not target.lower().startswith(
            ("rtsp://", "http://", "https://")
        )
        if isinstance(target, str) and self._is_file:
            from pathlib import Path

            if not Path(target).exists():
                raise VisionEngineError(f"Video file not found: {target}")
        capture = cv2.VideoCapture(target)
        if isinstance(target, str) and target.lower().startswith(("rtsp://", "http://", "https://")):
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not capture.isOpened():
            capture.release()
            raise VisionEngineError(f"Unable to open camera stream: {self.source_url}")
        self._capture = capture
        logger.info("Camera stream opened: %s (%s)", self.name, self.source_url)

    def read(self) -> Image | None:
        if self._capture is None:
            try:
                self.open()
            except VisionEngineError:
                time.sleep(self.RECONNECT_DELAY_SECONDS)
                return None
        assert self._capture is not None
        ok, frame = self._capture.read()
        if not ok or frame is None:
            if self._is_file:
                # Loop short demo clips so the gate never goes blind.
                self._capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, frame = self._capture.read()
                if not ok or frame is None:
                    return None
            else:
                logger.warning("Frame read failed for %s, reconnecting", self.name)
                self.close()
                time.sleep(self.RECONNECT_DELAY_SECONDS)
                return None
        if self.width and frame.shape[1] > self.width:
            ratio = self.width / frame.shape[1]
            frame = cv2.resize(
                frame,
                (self.width, max(1, int(frame.shape[0] * ratio))),
                interpolation=cv2.INTER_AREA,
            )
        return frame

    def close(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None


class DemoFrameSource(FrameSource):
    """Renders synthetic gate scenes for the offline demo camera."""

    def __init__(
        self,
        source_url: str,
        name: str,
        scenarios: tuple[DemoScenario, ...] = DEMO_SCENARIOS,
        interval_seconds: float | None = None,
        width: int = 1280,
        height: int = 720,
    ) -> None:
        super().__init__(source_url, name)
        self.scenarios = scenarios
        self.interval_seconds = interval_seconds or settings.CV_DEMO_INTERVAL_SECONDS
        self.width = width
        self.height = height
        self._started_at = time.monotonic()
        self._sequence = 0
        self._index = -1
        # Stagger cameras so entry and exit feeds do not show the same scene.
        self._offset = sum(ord(ch) for ch in source_url) % max(1, len(scenarios))

    def open(self) -> None:
        self._started_at = time.monotonic()
        logger.info("Demo camera started: %s", self.name)

    def close(self) -> None:
        return None

    def _current_scenario(self) -> DemoScenario:
        elapsed = time.monotonic() - self._started_at
        index = (
            int(elapsed / max(0.5, self.interval_seconds)) + self._offset
        ) % len(self.scenarios)
        self._index = index
        return self.scenarios[index]

    def read(self) -> Image | None:
        self._sequence += 1
        scenario = self._current_scenario()
        phase = ((time.monotonic() - self._started_at) % max(0.5, self.interval_seconds)) / max(
            0.5, self.interval_seconds
        )
        image, meta = render_scene(scenario, self.width, self.height, phase, self._sequence)
        self.last_meta = meta
        return image

    def meta(self) -> dict[str, Any]:
        return self.last_meta


def _gradient_background(width: int, height: int, sequence: int) -> Image:
    top = np.array([28, 22, 18], dtype=np.float32)  # BGR dusk sky
    bottom = np.array([58, 48, 42], dtype=np.float32)
    ramp = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None, None]
    background = (top[None, None, :] * (1 - ramp) + bottom[None, None, :] * ramp).astype(np.uint8)
    background = np.repeat(background, width, axis=1)

    # Asphalt with subtle noise for a realistic texture.
    road_top = int(height * 0.58)
    background[road_top:, :, :] = np.array([46, 44, 43], dtype=np.uint8)
    noise = np.random.default_rng(seed=7).integers(0, 14, size=(height - road_top, width, 1))
    background[road_top:, :, :] = np.clip(
        background[road_top:, :, :].astype(np.int16) + noise, 0, 255
    ).astype(np.uint8)
    return background


def _draw_gate_structure(image: Image, height: int, width: int) -> None:
    # Gate pillars and overhead beam.
    cv2.rectangle(image, (int(width * 0.06), int(height * 0.16)), (int(width * 0.10), int(height * 0.86)), (70, 78, 88), -1)
    cv2.rectangle(image, (int(width * 0.90), int(height * 0.16)), (int(width * 0.94), int(height * 0.86)), (70, 78, 88), -1)
    cv2.rectangle(image, (int(width * 0.06), int(height * 0.16)), (int(width * 0.94), int(height * 0.21)), (64, 72, 82), -1)
    cv2.putText(
        image,
        "GATEVISION  |  SMART GATE",
        (int(width * 0.30), int(height * 0.195)),
        cv2.FONT_HERSHEY_DUPLEX,
        0.7,
        (190, 200, 210),
        1,
        cv2.LINE_AA,
    )
    # Lane markings.
    for offset in range(0, width, 120):
        cv2.rectangle(
            image,
            (offset + 20, int(height * 0.90)),
            (offset + 80, int(height * 0.925)),
            (150, 150, 140),
            -1,
        )
    # Boom barrier (raised when demos are flowing).
    cv2.line(
        image,
        (int(width * 0.10), int(height * 0.40)),
        (int(width * 0.10), int(height * 0.68)),
        (52, 60, 70),
        14,
    )
    cv2.line(
        image,
        (int(width * 0.10), int(height * 0.42)),
        (int(width * 0.42), int(height * 0.30)),
        (40, 40, 220),
        8,
    )


def _draw_car(image: Image, center_x: int, base_y: int, scale: float = 1.0) -> tuple[BoundingBox, BoundingBox]:
    body_w = int(330 * scale)
    body_h = int(120 * scale)
    x1 = center_x - body_w // 2
    y1 = base_y - body_h
    x2 = center_x + body_w // 2
    y2 = base_y
    cv2.rectangle(image, (x1 + 40, y1 - int(60 * scale)), (x2 - 40, y1 + 10), (120, 120, 132), -1)
    cv2.rectangle(image, (x1 + 60, y1 - int(45 * scale)), (x2 - 60, y1), (60, 76, 92), -1)
    cv2.rectangle(image, (x1, y1), (x2, y2), (140, 142, 148), -1)
    cv2.rectangle(image, (x1, y1 + int(body_h * 0.55)), (x2, y2), (120, 122, 128), -1)
    for wheel_x in (x1 + int(60 * scale), x2 - int(60 * scale)):
        cv2.circle(image, (wheel_x, y2), int(28 * scale), (30, 30, 32), -1)
        cv2.circle(image, (wheel_x, y2), int(12 * scale), (110, 112, 118), -1)
    cv2.rectangle(image, (x1 + 20, y1 - 4), (x1 + 50, y1 + 6), (220, 235, 250), -1)
    cv2.rectangle(image, (x2 - 50, y1 - 4), (x2 - 20, y1 + 6), (220, 235, 250), -1)
    car_box = BoundingBox(x1, y1 - int(70 * scale), x2, y2)
    return car_box, BoundingBox(x1, y1, x2, y2)


def _draw_plate(image: Image, car_box: BoundingBox, plate_text: str) -> BoundingBox:
    plate_w = 220
    plate_h = 56
    cx, _ = car_box.center
    x1 = cx - plate_w // 2
    y1 = car_box.y2 - 84
    x2 = x1 + plate_w
    y2 = y1 + plate_h
    cv2.rectangle(image, (x1 - 6, y1 - 6), (x2 + 6, y2 + 6), (25, 25, 28), -1)
    cv2.rectangle(image, (x1, y1), (x2, y2), (238, 240, 242), -1)
    cv2.putText(
        image,
        plate_text.upper(),
        (x1 + 8, y2 - 16),
        cv2.FONT_HERSHEY_DUPLEX,
        0.95,
        (20, 20, 24),
        2,
        cv2.LINE_AA,
    )
    return BoundingBox(x1, y1, x2, y2)


def _draw_face(image: Image, center: tuple[int, int], radius: int = 46) -> BoundingBox:
    cx, cy = center
    cv2.circle(image, (cx, cy + radius + 80), radius + 90, (52, 58, 70), -1)  # torso
    cv2.circle(image, (cx, cy), radius, (168, 178, 190), -1)
    cv2.circle(image, (cx - 16, cy - 8), 5, (40, 40, 44), -1)
    cv2.circle(image, (cx + 16, cy - 8), 5, (40, 40, 44), -1)
    cv2.ellipse(image, (cx, cy + 18), (16, 8), 0, 0, 180, (90, 90, 96), 2)
    return BoundingBox(cx - radius, cy - radius, cx + radius, cy + radius)


def render_scene(
    scenario: DemoScenario, width: int, height: int, phase: float, sequence: int
) -> tuple[Image, dict[str, Any]]:
    """Render one synthetic frame plus the metadata used by mock detectors."""
    image = _gradient_background(width, height, sequence)
    _draw_gate_structure(image, height, width)

    # Gentle approach motion to keep the scene alive without breaking boxes.
    offset = int(40 * math.sin(phase * math.pi))
    car_center = width // 2 + offset
    base_y = int(height * 0.80)

    meta: dict[str, Any] = {
        "scenario": scenario.key,
        "description": scenario.description,
        "plate_text": scenario.plate_text,
        "plate_confidence": 0.93,
        "face_bboxes": [],
        "face_keys": [],
    }

    if scenario.plate_text:
        car_box, _ = _draw_car(image, car_center, base_y)
        plate_box = _draw_plate(image, car_box, scenario.plate_text)
        meta["plate_bbox"] = plate_box.as_dict()
        meta["car_bbox"] = car_box.as_dict()
        if scenario.face_key and scenario.face_in_car:
            face_center = (car_center, car_box.y1 + 14)
            face_box = _draw_face(image, face_center, radius=26)
            meta["face_bboxes"].append(face_box.as_dict())
            meta["face_keys"].append(scenario.face_key)
    elif scenario.face_key:
        face_center = (width // 2 + offset, int(height * 0.42))
        face_box = _draw_face(image, face_center, radius=52)
        meta["face_bboxes"].append(face_box.as_dict())
        meta["face_keys"].append(scenario.face_key)

    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    cv2.putText(
        image,
        timestamp,
        (int(width * 0.06), int(height * 0.95)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (210, 215, 220),
        1,
        cv2.LINE_AA,
    )
    cv2.putText(
        image,
        "DEMO FEED",
        (int(width * 0.78), int(height * 0.19)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (80, 200, 255),
        1,
        cv2.LINE_AA,
    )
    return image, meta
