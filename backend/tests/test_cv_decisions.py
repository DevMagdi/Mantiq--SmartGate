"""End-to-end tests of the vision pipeline and the access decision engine.

Mock mode scripts the detections, so these tests exercise the exact same
pipeline, decision rules, persistence and event publishing as production while
remaining deterministic and CPU-friendly.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.cv.demo_data import DEMO_SCENARIOS

API = "/api/v1"


def _frame(width: int = 960, height: int = 540) -> bytes:
    image = np.full((height, width, 3), 32, dtype=np.uint8)
    cv2.rectangle(image, (int(width * 0.1), int(height * 0.15)), (int(width * 0.9), int(height * 0.9)), (70, 70, 70), -1)
    cv2.putText(
        image,
        "GATEVISION TEST FRAME",
        (24, height - 28),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (230, 230, 230),
        2,
        cv2.LINE_AA,
    )
    ok, buffer = cv2.imencode(".png", image)
    assert ok
    return buffer.tobytes()


def _analyze(
    client: TestClient,
    headers: dict[str, str],
    gate_id: str,
    scenario: str | None = None,
) -> dict[str, Any]:
    data: dict[str, str] = {"gate_id": gate_id}
    if scenario:
        data["demo_scenario"] = scenario
    response = client.post(
        f"{API}/cv/analyze",
        headers=headers,
        data=data,
        files={"file": ("frame.png", _frame(), "image/png")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_pipeline_status(client: TestClient, admin_headers: dict[str, str]) -> None:
    status = client.get(f"{API}/cv/status", headers=admin_headers)
    assert status.status_code == 200
    body = status.json()
    assert body["mode"] == "mock"
    assert body["engine_ready"] is True
    assert body["plate_detector"] in {"mock", "yolo"}
    assert body["ocr_engine"] in {"mock", "easyocr", "paddleocr"}
    assert body["face_engine"] in {"mock", "insightface"}
    assert body["face_gallery_size"] >= 4
    assert body["similarity_threshold"] == settings.CV_FACE_SIMILARITY_THRESHOLD


def test_every_demo_scenario(
    client: TestClient, officer_headers: dict[str, str], demo: dict[str, Any]
) -> None:
    gate_id = demo["gate"]["id"]
    results: dict[str, dict[str, Any]] = {}
    for scenario in DEMO_SCENARIOS:
        body = _analyze(client, officer_headers, gate_id, scenario.key)
        results[scenario.key] = body
        assert body["decision"] == scenario.expected_decision, (scenario.key, body)
        assert body["access_log_id"] is not None
        assert body["detection_event_id"] is not None
        assert body["processing_ms"] is not None
        if scenario.plate_text:
            assert body["plate_text"] == scenario.plate_text
            assert body["plate_confidence"] is not None and body["plate_confidence"] > 0.5
            assert body["plate_snapshot_url"]

    assert results["resident-entry"]["reason_code"] == "registered_vehicle"
    assert results["resident-entry"]["access_method"] == "plate"
    assert results["visitor-permit"]["reason_code"] == "visitor_permit"
    assert results["unknown-vehicle"]["reason_code"] == "unknown_plate"
    assert results["blacklisted-plate"]["reason_code"] == "blacklist_plate"
    assert results["resident-pedestrian"]["face_matched"] is True
    assert results["resident-pedestrian"]["face_similarity"] > 0.45
    assert results["blocked-person"]["decision"] == "deny"
    assert results["known-face-unknown-car"]["decision"] == "review"
    assert results["known-face-unknown-car"]["face_matched"] is True
    assert results["suspended-resident"]["reason_code"] == "vehicle_suspended"


def test_snapshots_are_persisted(
    client: TestClient, officer_headers: dict[str, str], demo: dict[str, Any]
) -> None:
    body = _analyze(client, officer_headers, demo["gate"]["id"], "resident-entry")
    url: str = body["plate_snapshot_url"]
    assert url.startswith(settings.MEDIA_URL)
    relative = url[len(settings.MEDIA_URL) :].lstrip("/")
    path = Path(settings.MEDIA_ROOT) / relative
    assert path.is_file()
    assert path.stat().st_size > 0

    media = client.get(url)
    assert media.status_code == 200
    assert media.headers["content-type"] == "image/jpeg"


def test_plate_only_analysis_without_scenario(
    client: TestClient, officer_headers: dict[str, str], demo: dict[str, Any]
) -> None:
    """A raw upload in mock mode still produces a persisted, auditable record."""
    body = _analyze(client, officer_headers, demo["gate"]["id"])
    assert body["decision"] in {"unknown", "review", "deny", "allow"}
    assert body["access_log_id"] is not None
    log = client.get(
        f"{API}/access-logs/{body['access_log_id']}", headers=officer_headers
    ).json()
    assert log["access_method"] in {"plate", "face", "combined"}
    assert "Manual image analysis" in (log["notes"] or "")


def test_unknown_demo_scenario_rejected(
    client: TestClient, officer_headers: dict[str, str], demo: dict[str, Any]
) -> None:
    response = client.post(
        f"{API}/cv/analyze",
        headers=officer_headers,
        data={"gate_id": demo["gate"]["id"], "demo_scenario": "does-not-exist"},
        files={"file": ("frame.png", _frame(), "image/png")},
    )
    assert response.status_code == 400
    assert "demo scenario" in response.json()["error"]["message"].lower()

    bad_content = client.post(
        f"{API}/cv/analyze",
        headers=officer_headers,
        data={"gate_id": demo["gate"]["id"]},
        files={"file": ("frame.txt", b"not an image", "text/plain")},
    )
    assert bad_content.status_code == 400


def test_blacklist_entry_changes_the_decision(
    client: TestClient, officer_headers: dict[str, str], demo: dict[str, Any]
) -> None:
    compound_id = demo["compound"]["id"]
    gate_id = demo["gate"]["id"]
    entry = client.post(
        f"{API}/blacklist",
        headers=officer_headers,
        json={
            "compound_id": compound_id,
            "entry_type": "plate",
            "plate_number": "CAI 4821",
            "reason": "security",
            "description": "Temporary blockade for testing",
        },
    )
    assert entry.status_code == 201, entry.text
    try:
        denied = _analyze(client, officer_headers, gate_id, "resident-entry")
        assert denied["decision"] == "deny"
        assert denied["reason_code"] == "blacklist_plate"
    finally:
        client.delete(f"{API}/blacklist/{entry.json()['id']}", headers=officer_headers)

    allowed_again = _analyze(client, officer_headers, gate_id, "resident-entry")
    assert allowed_again["decision"] == "allow"


def test_revoked_permit_denies_visitor(
    client: TestClient, admin_headers: dict[str, str], demo: dict[str, Any]
) -> None:
    gate_id = demo["gate"]["id"]
    permits = client.get(f"{API}/permits?active_only=true", headers=admin_headers).json()["items"]
    permit = next(p for p in permits if (p.get("vehicle_plate") or "") == "GZ 5520")
    host = client.get(f"{API}/visitors/{permit['visitor_id']}", headers=admin_headers).json()
    revoked = client.post(
        f"{API}/permits/{permit['id']}/revoke",
        headers=admin_headers,
        json={"reason": "Vehicle replaced"},
    )
    assert revoked.status_code == 200
    try:
        body = _analyze(client, admin_headers, gate_id, "visitor-permit")
        assert body["decision"] == "deny"
        assert body["reason_code"] == "permit_revoked"
    finally:
        replacement = client.post(
            f"{API}/permits",
            headers=admin_headers,
            json={
                "visitor_id": host["id"],
                "host_unit_id": host["host_unit_id"],
                "vehicle_plate": "GZ 5520",
                "start_at": "2026-01-01T00:00:00Z",
                "end_at": "2030-01-01T00:00:00Z",
            },
        )
        assert replacement.status_code == 201, replacement.text


def test_manual_review_override_and_confirm(
    client: TestClient, officer_headers: dict[str, str], demo: dict[str, Any]
) -> None:
    body = _analyze(client, officer_headers, demo["gate"]["id"], "known-face-unknown-car")
    assert body["decision"] == "review"
    log_id = body["access_log_id"]

    confirmed = client.post(f"{API}/cv/analysis/{log_id}/confirm", headers=officer_headers)
    assert confirmed.status_code == 200
    assert "acknowledged" in confirmed.json()["message"].lower()

    override = client.post(
        f"{API}/access-logs/{log_id}/override",
        headers=officer_headers,
        json={
            "decision": "allow",
            "reason": "Resident identity confirmed against the unit list",
            "open_gate": True,
            "notes": "Cashless visitor lane",
        },
    )
    assert override.status_code == 200, override.text
    updated = override.json()
    assert updated["decision"] == "allow"
    assert updated["is_overridden"] is True
    assert updated["override_reason"].startswith("Resident identity")
    assert updated["override_by_id"] is not None
    assert updated["gate_opened"] is True

    already_logged = client.post(
        f"{API}/access-logs/{log_id}/override",
        headers=officer_headers,
        json={"decision": "deny", "reason": "Changed my mind"},
    )
    assert already_logged.status_code == 200

    unknown_log = client.post(
        f"{API}/cv/analysis/{uuid.uuid4()}/confirm", headers=officer_headers
    )
    assert unknown_log.status_code == 404


def test_gate_commands_and_camera_health(
    client: TestClient, officer_headers: dict[str, str], demo: dict[str, Any]
) -> None:
    opened = client.post(
        f"{API}/gates/{demo['gate']['id']}/command",
        headers=officer_headers,
        json={"action": "open", "reason": "Priority ambulance"},
    )
    assert opened.status_code == 200
    assert opened.json()["accepted"] is True
    assert opened.json()["action"] == "open"

    invalid = client.post(
        f"{API}/gates/{demo['gate']['id']}/command",
        headers=officer_headers,
        json={"action": "detonate", "reason": "invalid action"},
    )
    assert invalid.status_code == 422

    health = client.get(f"{API}/cv/camera-health", headers=officer_headers).json()
    assert health["total"] == 3
    assert health["online"] + health["offline"] + health["disabled"] == 3

    workers = client.get(f"{API}/cv/workers", headers=officer_headers).json()
    assert workers["in_process"] is False

    gallery = client.get(f"{API}/cv/gallery", headers=officer_headers).json()
    assert gallery["total_embeddings"] >= 4
    assert gallery["enrolled_residents"] >= 3
    assert gallery["model_name"]
    assert gallery["threshold"] == settings.CV_FACE_SIMILARITY_THRESHOLD

    refreshed = client.post(f"{API}/cv/refresh-gallery", headers=officer_headers)
    assert refreshed.status_code == 200

    warmed = client.post(f"{API}/cv/warmup", headers=officer_headers)
    assert warmed.status_code == 200
    assert warmed.json()["engine_ready"] is True


def test_resident_cannot_analyze(
    client: TestClient, resident_headers: dict[str, str], demo: dict[str, Any]
) -> None:
    response = client.post(
        f"{API}/cv/analyze",
        headers=resident_headers,
        data={"gate_id": demo["gate"]["id"]},
        files={"file": ("frame.png", _frame(), "image/png")},
    )
    assert response.status_code == 403
    assert client.get(f"{API}/cv/status", headers=resident_headers).status_code == 403


@pytest.mark.parametrize("size", [(320, 240), (1920, 1080)])
def test_pipeline_handles_different_resolutions(
    client: TestClient,
    officer_headers: dict[str, str],
    demo: dict[str, Any],
    size: tuple[int, int],
) -> None:
    width, height = size
    body = client.post(
        f"{API}/cv/analyze",
        headers=officer_headers,
        data={"gate_id": demo["gate"]["id"], "demo_scenario": "resident-entry"},
        files={"file": ("frame.png", _frame(width, height), "image/png")},
    )
    assert body.status_code == 200, body.text
    assert body.json()["decision"] == "allow"
