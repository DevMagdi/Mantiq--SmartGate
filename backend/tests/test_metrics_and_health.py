"""Prometheus metrics, readiness probes and production config guards."""

from __future__ import annotations

from typing import Any

from starlette.testclient import TestClient

from app.core.config import Settings

API = "/api/v1"


def _png(width: int = 320, height: int = 240) -> bytes:
    import cv2
    import numpy as np

    rng = np.random.default_rng(3)
    image = rng.integers(40, 210, size=(height, width, 3), dtype=np.uint8)
    cv2.rectangle(image, (80, 90), (240, 160), (30, 30, 30), -1)
    ok, buffer = cv2.imencode(".png", image)
    assert ok
    return buffer.tobytes()


# --------------------------------------------------------------------------- #
# Probes
# --------------------------------------------------------------------------- #


def test_liveness_probe_is_cheap_and_public(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"]

    alias = client.get("/health/live")
    assert alias.status_code == 200
    assert alias.json()["status"] == "ok"


def test_readiness_reports_every_dependency(client: TestClient) -> None:
    response = client.get("/health/ready")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ready"
    assert body["database"] is True
    checks = body["checks"]
    assert checks["database"]["ok"] is True
    assert checks["redis"]["enabled"] is False
    assert checks["vision"]["mode"] == "mock"
    assert checks["vision"]["engine_ready"] is True
    assert checks["vision"]["face_gallery_size"] >= 4
    assert "default_driver" in checks["barrier"]
    assert checks["maintenance"]["enabled"] is True
    assert isinstance(body["warnings"], list)


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #


def test_metrics_endpoint_exposes_http_request_metrics(client: TestClient) -> None:
    client.get("/health")
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    text = response.text
    assert "gatevision_http_requests_total" in text
    assert "gatevision_http_request_duration_seconds_bucket" in text
    assert "gatevision_cv_engine_ready" in text
    assert "gatevision_app_info" in text
    # Route templates (not raw paths) are used as labels.
    assert 'route="/health"' in text
    assert "gatevision_http_requests_total{method=\"GET\",route=\"/metrics\"" not in text
    assert "python_info" not in text


def test_metrics_capture_decisions_and_barrier_commands(
    client: TestClient, admin_headers: dict[str, str], demo: dict[str, Any]
) -> None:
    analyzed = client.post(
        f"{API}/cv/analyze",
        headers=admin_headers,
        files={"file": ("frame.png", _png(), "image/png")},
        data={"gate_id": demo["gate"]["id"], "demo_scenario": "resident-entry"},
    )
    assert analyzed.status_code == 200, analyzed.text

    opened = client.post(
        f"{API}/gates/{demo['gate']['id']}/command",
        headers=admin_headers,
        json={"action": "open", "reason": "metrics probe"},
    )
    assert opened.status_code == 200

    text = client.get("/metrics").text
    assert "gatevision_access_decisions_total" in text
    assert 'reason_code="registered_vehicle"' in text
    assert "gatevision_barrier_commands_total" in text
    assert 'action="open"' in text
    assert "gatevision_vision_results_total" in text


# --------------------------------------------------------------------------- #
# Production configuration guards
# --------------------------------------------------------------------------- #


def _prod_settings(**overrides: Any) -> Settings:
    base = dict(
        ENVIRONMENT="production",
        DEBUG=False,
        SECRET_KEY="x" * 64,
        CORS_ORIGINS=["https://gatevision.example.com"],
        TRUSTED_HOSTS=["gatevision.example.com"],
    )
    base.update(overrides)
    return Settings(**base)


def test_production_rejects_placeholder_secret() -> None:
    insecure = _prod_settings(SECRET_KEY="change-me-please")
    try:
        insecure.validate_production()
    except RuntimeError as exc:
        assert "SECRET_KEY" in str(exc)
    else:  # pragma: no cover - regression guard
        raise AssertionError("placeholder secret must not boot in production")


def test_production_rejects_wildcard_cors_and_debug() -> None:
    for overrides in ({"CORS_ORIGINS": ["*"]}, {"DEBUG": True}):
        settings = _prod_settings(**overrides)
        try:
            settings.validate_production()
        except RuntimeError:
            continue
        raise AssertionError(f"{overrides} must not boot in production")


def test_production_warns_but_starts_for_soft_problems() -> None:
    settings = _prod_settings(
        DATABASE_URL="sqlite+aiosqlite:///./gatevision.db",
        CV_MODE="mock",
        BARRIER_DRIVER="webhook",
        BARRIER_WEBHOOK_URL="http://controller.local/hook",
    )
    warnings = settings.validate_production()
    joined = " ".join(warnings)
    assert "SQLite" in joined
    assert "CV_MODE=mock" in joined
    assert "http://" in joined


def test_development_config_is_never_blocked() -> None:
    dev = Settings(ENVIRONMENT="development", SECRET_KEY="short")
    assert dev.validate_production()
