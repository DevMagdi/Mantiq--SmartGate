"""Per-compound operational policy parsed from ``compound.settings``.

Every gate in a compound shares one policy document.  Keeping it here (instead
of scattering ``settings.get(...)`` calls) gives us:

* one validated schema shared by the API, the decision engine and the workers,
* sane clamps so a typo in the dashboard cannot disable security,
* a single place to add new knobs without touching routers.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping

from app.core.config import settings
from app.core.logging import get_logger
from app.models.enums import AccessDecision

logger = get_logger(__name__)

SUPPORTED_BARRIER_DRIVERS = ("simulator", "webhook", "mqtt", "gpio")
SECRET_PLACEHOLDER = "********"


def _as_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _as_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _as_str(value: Any, default: str | None = None) -> str | None:
    if value is None:
        return default
    text = str(value).strip()
    return text or default


@dataclass(frozen=True, slots=True)
class VisionPolicy:
    """Thresholds used by the ANPR / face pipeline for one compound."""

    plate_confidence_threshold: float = 0.35
    ocr_min_confidence: float = 0.45
    face_similarity_threshold: float = 0.45
    face_min_quality: float = 55.0
    face_min_resolution: int = 200
    face_min_blur: float = 40.0
    face_min_brightness: float = 30.0
    face_max_brightness: float = 235.0
    face_min_face_ratio: float = 0.05
    max_embeddings_per_resident: int = 3
    duplicate_similarity_threshold: float = 0.90
    reject_duplicate_enrollment: bool = True

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> "VisionPolicy":
        raw = dict(data or {})
        defaults = cls()
        return cls(
            plate_confidence_threshold=_as_float(
                raw.get("plate_confidence_threshold"),
                defaults.plate_confidence_threshold,
                0.05,
                0.95,
            ),
            ocr_min_confidence=_as_float(
                raw.get("ocr_min_confidence"), defaults.ocr_min_confidence, 0.05, 0.98
            ),
            face_similarity_threshold=_as_float(
                raw.get("face_similarity_threshold"),
                defaults.face_similarity_threshold,
                0.20,
                0.85,
            ),
            face_min_quality=_as_float(
                raw.get("face_min_quality"), defaults.face_min_quality, 0.0, 100.0
            ),
            face_min_resolution=_as_int(
                raw.get("face_min_resolution"), defaults.face_min_resolution, 80, 2000
            ),
            face_min_blur=_as_float(
                raw.get("face_min_blur"), defaults.face_min_blur, 0.0, 500.0
            ),
            face_min_brightness=_as_float(
                raw.get("face_min_brightness"), defaults.face_min_brightness, 0.0, 254.0
            ),
            face_max_brightness=_as_float(
                raw.get("face_max_brightness"), defaults.face_max_brightness, 1.0, 255.0
            ),
            face_min_face_ratio=_as_float(
                raw.get("face_min_face_ratio"), defaults.face_min_face_ratio, 0.01, 0.9
            ),
            max_embeddings_per_resident=_as_int(
                raw.get("max_embeddings_per_resident"),
                defaults.max_embeddings_per_resident,
                1,
                10,
            ),
            duplicate_similarity_threshold=_as_float(
                raw.get("duplicate_similarity_threshold"),
                defaults.duplicate_similarity_threshold,
                0.50,
                0.995,
            ),
            reject_duplicate_enrollment=_as_bool(
                raw.get("reject_duplicate_enrollment"), defaults.reject_duplicate_enrollment
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "plate_confidence_threshold": self.plate_confidence_threshold,
            "ocr_min_confidence": self.ocr_min_confidence,
            "face_similarity_threshold": self.face_similarity_threshold,
            "face_min_quality": self.face_min_quality,
            "face_min_resolution": self.face_min_resolution,
            "face_min_blur": self.face_min_blur,
            "face_min_brightness": self.face_min_brightness,
            "face_max_brightness": self.face_max_brightness,
            "face_min_face_ratio": self.face_min_face_ratio,
            "max_embeddings_per_resident": self.max_embeddings_per_resident,
            "duplicate_similarity_threshold": self.duplicate_similarity_threshold,
            "reject_duplicate_enrollment": self.reject_duplicate_enrollment,
        }


@dataclass(frozen=True, slots=True)
class AccessPolicy:
    """Decision-engine behaviour for one compound."""

    auto_open_barrier: bool = True
    allow_face_only_entry: bool = True
    unknown_vehicle_decision: AccessDecision = AccessDecision.UNKNOWN
    require_face_for_vehicle: bool = False
    exit_grace_minutes: int = 30
    allow_blacklist_exit: bool = False
    allow_visitor_exit_after_expiry: bool = True

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> "AccessPolicy":
        raw = dict(data or {})
        defaults = cls()
        decision_raw = _as_str(raw.get("unknown_vehicle_decision"), "unknown") or "unknown"
        try:
            unknown_decision = AccessDecision(decision_raw)
        except ValueError:
            unknown_decision = defaults.unknown_vehicle_decision
        if unknown_decision not in {AccessDecision.UNKNOWN, AccessDecision.REVIEW, AccessDecision.DENY}:
            unknown_decision = defaults.unknown_vehicle_decision
        return cls(
            auto_open_barrier=_as_bool(raw.get("auto_open_barrier"), defaults.auto_open_barrier),
            allow_face_only_entry=_as_bool(
                raw.get("allow_face_only_entry"), defaults.allow_face_only_entry
            ),
            unknown_vehicle_decision=unknown_decision,
            require_face_for_vehicle=_as_bool(
                raw.get("require_face_for_vehicle"), defaults.require_face_for_vehicle
            ),
            exit_grace_minutes=_as_int(
                raw.get("exit_grace_minutes"), defaults.exit_grace_minutes, 0, 720
            ),
            allow_blacklist_exit=_as_bool(
                raw.get("allow_blacklist_exit"), defaults.allow_blacklist_exit
            ),
            allow_visitor_exit_after_expiry=_as_bool(
                raw.get("allow_visitor_exit_after_expiry"),
                defaults.allow_visitor_exit_after_expiry,
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "auto_open_barrier": self.auto_open_barrier,
            "allow_face_only_entry": self.allow_face_only_entry,
            "unknown_vehicle_decision": self.unknown_vehicle_decision.value,
            "require_face_for_vehicle": self.require_face_for_vehicle,
            "exit_grace_minutes": self.exit_grace_minutes,
            "allow_blacklist_exit": self.allow_blacklist_exit,
            "allow_visitor_exit_after_expiry": self.allow_visitor_exit_after_expiry,
        }


@dataclass(frozen=True, slots=True)
class WebhookConfig:
    url: str | None = None
    secret: str | None = None
    timeout_seconds: float = 3.0
    retries: int = 2
    verify_tls: bool = True


@dataclass(frozen=True, slots=True)
class MqttConfig:
    host: str = "localhost"
    port: int = 1883
    topic: str = "gatevision/{gate}/command"
    qos: int = 1
    username: str | None = None
    password: str | None = None
    tls: bool = False
    client_id: str = "gatevision-api"
    simulate: bool = True


@dataclass(frozen=True, slots=True)
class GpioConfig:
    pin_count: int = 1
    open_pin: int = 17
    close_pin: int = 27
    hold_pin: int | None = None
    active_high: bool = True
    pulse_seconds: float = 0.6
    backend: str = "gpiozero"
    simulate: bool = True


@dataclass(frozen=True, slots=True)
class BarrierPolicy:
    """Which actuator drives the barrier and how it is configured."""

    driver: str = "simulator"
    webhook: WebhookConfig = field(default_factory=WebhookConfig)
    mqtt: MqttConfig = field(default_factory=MqttConfig)
    gpio: GpioConfig = field(default_factory=GpioConfig)
    simulator_latency_ms: int = 40
    simulator_failure_rate: float = 0.0

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> "BarrierPolicy":
        raw = dict(data or {})
        defaults = cls()
        driver = (_as_str(raw.get("driver"), defaults.driver) or "simulator").lower()
        if driver not in SUPPORTED_BARRIER_DRIVERS:
            logger.warning("Unknown barrier driver %r, falling back to simulator", driver)
            driver = "simulator"
        webhook_raw = dict(raw.get("webhook") or {})
        mqtt_raw = dict(raw.get("mqtt") or {})
        gpio_raw = dict(raw.get("gpio") or {})
        return cls(
            driver=driver,
            webhook=WebhookConfig(
                url=_as_str(webhook_raw.get("url")),
                secret=_as_str(webhook_raw.get("secret")),
                timeout_seconds=_as_float(webhook_raw.get("timeout_seconds"), 3.0, 0.5, 30.0),
                retries=_as_int(webhook_raw.get("retries"), 2, 0, 5),
                verify_tls=_as_bool(webhook_raw.get("verify_tls"), True),
            ),
            mqtt=MqttConfig(
                host=_as_str(mqtt_raw.get("host"), "localhost") or "localhost",
                port=_as_int(mqtt_raw.get("port"), 1883, 1, 65535),
                topic=_as_str(mqtt_raw.get("topic"), "gatevision/{gate}/command")
                or "gatevision/{gate}/command",
                qos=_as_int(mqtt_raw.get("qos"), 1, 0, 2),
                username=_as_str(mqtt_raw.get("username")),
                password=_as_str(mqtt_raw.get("password")),
                tls=_as_bool(mqtt_raw.get("tls"), False),
                client_id=_as_str(mqtt_raw.get("client_id"), "gatevision-api") or "gatevision-api",
                simulate=_as_bool(mqtt_raw.get("simulate"), True),
            ),
            gpio=GpioConfig(
                open_pin=_as_int(gpio_raw.get("open_pin"), 17, 1, 40),
                close_pin=_as_int(gpio_raw.get("close_pin"), 27, 1, 40),
                hold_pin=(
                    _as_int(gpio_raw.get("hold_pin"), 22, 1, 40)
                    if gpio_raw.get("hold_pin") not in (None, "")
                    else None
                ),
                active_high=_as_bool(gpio_raw.get("active_high"), True),
                pulse_seconds=_as_float(gpio_raw.get("pulse_seconds"), 0.6, 0.05, 10.0),
                backend=_as_str(gpio_raw.get("backend"), "gpiozero") or "gpiozero",
                simulate=_as_bool(gpio_raw.get("simulate"), True),
            ),
            simulator_latency_ms=_as_int(raw.get("simulator_latency_ms"), 40, 0, 5000),
            simulator_failure_rate=_as_float(raw.get("simulator_failure_rate"), 0.0, 0.0, 1.0),
        )

    def to_dict(self, *, mask_secrets: bool = True) -> dict[str, Any]:
        return {
            "driver": self.driver,
            "simulator_latency_ms": self.simulator_latency_ms,
            "simulator_failure_rate": self.simulator_failure_rate,
            "webhook": {
                "url": self.webhook.url,
                "secret": SECRET_PLACEHOLDER if (mask_secrets and self.webhook.secret) else self.webhook.secret,
                "timeout_seconds": self.webhook.timeout_seconds,
                "retries": self.webhook.retries,
                "verify_tls": self.webhook.verify_tls,
            },
            "mqtt": {
                "host": self.mqtt.host,
                "port": self.mqtt.port,
                "topic": self.mqtt.topic,
                "qos": self.mqtt.qos,
                "username": self.mqtt.username,
                "password": SECRET_PLACEHOLDER if (mask_secrets and self.mqtt.password) else self.mqtt.password,
                "tls": self.mqtt.tls,
                "client_id": self.mqtt.client_id,
                "simulate": self.mqtt.simulate,
            },
            "gpio": {
                "open_pin": self.gpio.open_pin,
                "close_pin": self.gpio.close_pin,
                "hold_pin": self.gpio.hold_pin,
                "active_high": self.gpio.active_high,
                "pulse_seconds": self.gpio.pulse_seconds,
                "backend": self.gpio.backend,
                "simulate": self.gpio.simulate,
            },
        }


@dataclass(frozen=True, slots=True)
class CompoundPolicy:
    """Complete operational policy for one compound."""

    vision: VisionPolicy = field(default_factory=VisionPolicy)
    access: AccessPolicy = field(default_factory=AccessPolicy)
    barrier: BarrierPolicy = field(default_factory=BarrierPolicy)

    @classmethod
    def from_settings(cls, document: Mapping[str, Any] | None) -> "CompoundPolicy":
        """Parse a compound settings document, tolerating legacy flat keys."""
        raw = dict(document or {})
        vision_raw = dict(raw.get("vision") or {})
        access_raw = dict(raw.get("access") or {})
        barrier_raw = dict(raw.get("barrier") or {})

        # Legacy flat keys (v1 settings) still work and are merged into access.
        for legacy in (
            "auto_open_barrier",
            "allow_face_only_entry",
            "unknown_vehicle_decision",
            "require_face_for_vehicle",
            "exit_grace_minutes",
        ):
            if legacy in raw and legacy not in access_raw:
                access_raw[legacy] = raw[legacy]
        if raw.get("gate_webhook_url") and not barrier_raw.get("driver"):
            barrier_raw["driver"] = "webhook"
            barrier_raw.setdefault("webhook", {})
            barrier_raw["webhook"] = {
                **dict(barrier_raw.get("webhook") or {}),
                "url": raw["gate_webhook_url"],
            }
        # Vision defaults come from the process settings so a deployment can
        # tune every compound at once, then override per compound.
        vision_raw.setdefault(
            "face_similarity_threshold", settings.CV_FACE_SIMILARITY_THRESHOLD
        )
        vision_raw.setdefault(
            "plate_confidence_threshold", settings.CV_PLATE_CONFIDENCE_THRESHOLD
        )
        vision_raw.setdefault("ocr_min_confidence", settings.CV_OCR_MIN_CONFIDENCE)
        return cls(
            vision=VisionPolicy.from_mapping(vision_raw),
            access=AccessPolicy.from_mapping(access_raw),
            barrier=BarrierPolicy.from_mapping(barrier_raw),
        )

    def to_dict(self, *, mask_secrets: bool = True) -> dict[str, Any]:
        return {
            "vision": self.vision.to_dict(),
            "access": self.access.to_dict(),
            "barrier": self.barrier.to_dict(mask_secrets=mask_secrets),
        }

    def with_vision(self, **overrides: Any) -> "CompoundPolicy":
        """Return a copy with vision overrides (used by request-level tuning)."""
        return replace(self, vision=replace(self.vision, **overrides))

DEFAULT_POLICY = CompoundPolicy()


def policy_from_settings(document: Mapping[str, Any] | None) -> CompoundPolicy:
    """Module-level helper mirroring :meth:`CompoundPolicy.from_settings`."""
    return CompoundPolicy.from_settings(document)


def mask_secrets_in_settings(document: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return a copy of the document with barrier secrets masked.

    Used on every compound response so a webhook HMAC secret or MQTT password
    never leaves the server, even in the admin listing.
    """
    raw = dict(document or {})
    barrier = raw.get("barrier")
    if isinstance(barrier, dict):
        barrier = {**barrier}
        for section, key in (("webhook", "secret"), ("mqtt", "password")):
            block = barrier.get(section)
            if isinstance(block, dict) and block.get(key):
                barrier[section] = {**block, key: SECRET_PLACEHOLDER}
        raw["barrier"] = barrier
    if raw.get("gate_webhook_secret"):
        raw["gate_webhook_secret"] = SECRET_PLACEHOLDER
    return raw


def mask_settings(document: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return the settings document with barrier secrets masked for API output."""
    raw = dict(document or {})
    policy = CompoundPolicy.from_settings(raw)
    merged = {**raw, **policy.to_dict(mask_secrets=True)}
    return merged


__all__ = [
    "AccessPolicy",
    "BarrierPolicy",
    "CompoundPolicy",
    "DEFAULT_POLICY",
    "GpioConfig",
    "MqttConfig",
    "SECRET_PLACEHOLDER",
    "SUPPORTED_BARRIER_DRIVERS",
    "VisionPolicy",
    "WebhookConfig",
    "mask_secrets_in_settings",
    "mask_settings",
    "policy_from_settings",
]
