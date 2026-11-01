"""Frame sources: RTSP/USB/file cameras and a synthetic demo renderer.

Real deployments spend most of their debugging time here, so this module is
deliberately defensive:

* RTSP is opened over TCP with explicit open/read timeouts (FFmpeg honours both
  properties for the ``rtsp`` backend).
* Reconnection uses exponential backoff and never busy-loops the CPU.
* ``${ENV_VAR}`` placeholders inside a camera URL are expanded from the process
  environment, so camera passwords live in the compose/secrets file instead of
  the database.
* Every source exposes :meth:`FrameSource.stats` (frames, reconnects, failures,
  last frame time) which the API and the Live Monitor surface as camera health.
"""

from __future__ import annotations

import math
import os
import re
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

_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")
_NETWORK_SCHEMES = ("rtsp://", "rtsps://", "http://", "https://")


def expand_env_source(url: str) -> str:
    """Expand ``${VAR}`` placeholders inside a camera URL.

    Missing variables are left untouched so the failure is visible in the
    camera health panel instead of silently producing an empty URL.
    """
    if not url or "${" not in url:
        return url

    def _replace(match: re.Match[str]) -> str:
        name = match.group(1)
        value = os.environ.get(name)
        return value if value is not None else match.group(0)

    return _ENV_PATTERN.sub(_replace, url)


def redact_source(url: str) -> str:
    """Hide RTSP credentials before a URL is logged or returned by the API."""
    if "@" not in url or "://" not in url:
        return url
    scheme, _, rest = url.partition("://")
    credentials, at, host = rest.rpartition("@")
    if not at:
        return url
    user = credentials.split(":", 1)[0]
    return f"{scheme}://{user}:***@{host}"


def is_network_source(url: str) -> bool:
    return url.strip().lower().startswith(_NETWORK_SCHEMES)


def normalise_capture_target(url: str) -> int | str:
    """Translate a camera ``source_url`` into an OpenCV capture target.

    Supported forms::

        rtsp://user:pass@host:554/Streaming/Channels/101
        http://host/video.mjpg
        0                 (USB camera index)
        usb://1           (explicit USB camera index)
        file:///data/clip.mp4
        ./clips/entry.mp4
    """
    value = expand_env_source(url).strip()
    lowered = value.lower()
    if lowered.startswith("usb://"):
        index = value[6:]
        if not index.isdigit():
            raise VisionEngineError(f"Invalid USB camera index in '{redact_source(url)}'")
        return int(index)
    if lowered.startswith("file://"):
        return value[7:]
    if value.isdigit():
        return int(value)
    return value


class FrameSource(ABC):
    """A pull-based camera stream."""

    def __init__(self, source_url: str, name: str) -> None:
        self.source_url = source_url
        self.name = name
        self.last_meta: dict[str, Any] = {}
        self.frames_read = 0
        self.failures = 0
        self.reconnects = 0
        self.last_frame_at: datetime | None = None
        self.connected_at: datetime | None = None

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

    def stats(self) -> dict[str, Any]:
        """Return counters used by the camera health endpoints."""
        return {
            "frames_read": self.frames_read,
            "failures": self.failures,
            "reconnects": self.reconnects,
            "last_frame_at": self.last_frame_at.isoformat() if self.last_frame_at else None,
            "connected_at": self.connected_at.isoformat() if self.connected_at else None,
        }


class OpenCVFrameSource(FrameSource):
    """OpenCV backed source supporting RTSP, HTTP, USB indexes and video files.

    ``read()`` never raises and never blocks indefinitely: it retries the
    connection with exponential backoff and returns ``None`` while the camera is
    unavailable, which lets the worker keep its slot and report health instead of
    dying (and needing a supervisor restart).
    """

    def __init__(
        self,
        source_url: str,
        name: str,
        width: int | None = None,
        *,
        reconnect_delay: float | None = None,
        max_delay: float | None = None,
        transport: str | None = None,
        open_timeout_ms: int | None = None,
        read_timeout_ms: int | None = None,
    ) -> None:
        super().__init__(source_url, name)
        self.width = width or settings.CV_FRAME_WIDTH
        self.reconnect_delay = max(
            0.1,
            settings.CV_RECONNECT_DELAY_SECONDS if reconnect_delay is None else reconnect_delay,
        )
        self.max_delay = max(
            self.reconnect_delay,
            settings.CV_RECONNECT_MAX_DELAY_SECONDS if max_delay is None else max_delay,
        )
        self.transport = (transport or settings.CV_RTSP_TRANSPORT or "tcp").lower()
        self.open_timeout_ms = (
            settings.CV_RTSP_OPEN_TIMEOUT_MS if open_timeout_ms is None else open_timeout_ms
        )
        self.read_timeout_ms = (
            settings.CV_RTSP_READ_TIMEOUT_MS if read_timeout_ms is None else read_timeout_ms
        )
        self._capture: cv2.VideoCapture | None = None
        self._is_file = False
        self._delay = self.reconnect_delay
        self._open_failures = 0
        self.last_error: str | None = None

    # ------------------------------------------------------------------ opening
    def _apply_ffmpeg_options(self) -> None:
        """Configure FFmpeg before ``cv2.VideoCapture`` opens an RTSP stream.

        OpenCV reads ``OPENCV_FFMPEG_CAPTURE_OPTIONS`` when the capture is
        created; TCP transport plus timeouts is the difference between a camera
        that recovers from a cable pull and one that hangs the worker forever.
        """
        if not is_network_source(self.source_url):
            return
        options = ["rtsp_transport;tcp"] if self.transport == "tcp" else []
        if self.transport == "udp":
            options = ["rtsp_transport;udp"]
        options.append(f"stimeout;{max(1000, self.read_timeout_ms) * 1000}")
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "|".join(options)

    def target(self) -> int | str:
        return normalise_capture_target(self.source_url)

    def open(self) -> None:
        if self._capture is not None:
            return
        target = self.target()
        self._is_file = isinstance(target, str) and not is_network_source(target)
        if isinstance(target, str) and self._is_file:
            from pathlib import Path

            if not Path(target).exists():
                raise VisionEngineError(f"Video file not found: {target}")
        self._apply_ffmpeg_options()
        params: list[int] = []
        if is_network_source(self.source_url):
            params = [
                int(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC),
                int(self.open_timeout_ms),
                int(cv2.CAP_PROP_READ_TIMEOUT_MSEC),
                int(self.read_timeout_ms),
            ]
        capture = (
            cv2.VideoCapture(target, cv2.CAP_FFMPEG, params)
            if params
            else cv2.VideoCapture(target)
        )
        if isinstance(target, str) and is_network_source(target):
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not capture.isOpened():
            capture.release()
            self.last_error = f"Unable to open camera stream: {redact_source(self.source_url)}"
            raise VisionEngineError(self.last_error)
        self._capture = capture
        self._delay = self.reconnect_delay
        self._open_failures = 0
        self.connected_at = datetime.now(UTC)
        self.last_error = None
        logger.info(
            "Camera stream opened: %s (%s, transport=%s)",
            self.name,
            redact_source(self.source_url),
            self.transport,
        )

    # ------------------------------------------------------------------ reading
    def read(self) -> Image | None:
        if self._capture is None:
            try:
                self.open()
            except VisionEngineError as exc:
                return self._fail(str(exc))
        assert self._capture is not None
        ok, frame = self._capture.read()
        if not ok or frame is None:
            if self._is_file:
                # Loop short clips so a file-backed demo never goes blind.
                self._capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, frame = self._capture.read()
            if not ok or frame is None:
                return self._fail("Frame read failed; reconnecting")
        if self.width and frame.shape[1] > self.width:
            ratio = self.width / frame.shape[1]
            frame = cv2.resize(
                frame,
                (self.width, max(1, int(frame.shape[0] * ratio))),
                interpolation=cv2.INTER_AREA,
            )
        self.frames_read += 1
        self.last_frame_at = datetime.now(UTC)
        self.last_error = None
        return frame

    def _fail(self, error: str) -> None:
        """Release the stream, back off and report the failure."""
        self.failures += 1
        self.last_error = error
        self.close()
        delay = min(self._delay, self.max_delay)
        logger.warning(
            "Camera %s unavailable (%s); retrying in %.1fs", self.name, error, delay
        )
        time.sleep(delay)
        self._delay = min(self._delay * 2, self.max_delay)
        return None

    def close(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None
            self.reconnects += 1
            self.connected_at = None

    def stats(self) -> dict[str, Any]:
        payload = super().stats()
        payload.update(
            {
                "kind": "opencv",
                "transport": self.transport if is_network_source(self.source_url) else "local",
                "source": redact_source(self.source_url),
                "connected": self._capture is not None,
                "last_error": self.last_error,
            }
        )
        return payload


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
        self.connected_at = datetime.now(UTC)
        logger.warning("DEMO camera started: %s (synthetic frames, not a real stream)", self.name)

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
        self.frames_read += 1
        self.last_frame_at = datetime.now(UTC)
        return image

    def stats(self) -> dict[str, Any]:
        payload = super().stats()
        payload.update({"kind": "demo", "synthetic": True, "source": "demo"})
        return payload


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


__all__ = [
    "DemoFrameSource",
    "FrameSource",
    "OpenCVFrameSource",
    "expand_env_source",
    "is_network_source",
    "normalise_capture_target",
    "redact_source",
    "render_scene",
]
