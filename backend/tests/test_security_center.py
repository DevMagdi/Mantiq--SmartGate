"""Security centre behaviour: blacklist lifecycle and the biometric gallery."""

from __future__ import annotations

import io

from starlette.testclient import TestClient


def _png_bytes() -> bytes:
    """Textured synthetic portrait so the enrollment quality gates pass."""
    import cv2
    import numpy as np

    rng = np.random.default_rng(11)
    image = rng.integers(60, 200, size=(480, 480, 3), dtype=np.uint8)
    cv2.ellipse(image, (240, 240), (95, 120), 0, 0, 360, (185, 175, 165), -1)
    cv2.circle(image, (215, 225), 7, (25, 25, 25), -1)
    cv2.circle(image, (265, 225), 7, (25, 25, 25), -1)
    cv2.ellipse(image, (240, 285), (30, 12), 0, 0, 180, (60, 50, 50), 3)
    ok, buffer = cv2.imencode(".png", image)
    assert ok
    return buffer.tobytes()


def test_blacklist_lists_all_states_and_deactivates(
    client: TestClient, admin_headers: dict[str, str], demo: dict[str, object]
) -> None:
    created = client.post(
        "/api/v1/blacklist",
        headers=admin_headers,
        json={
            "compound_id": demo["compound"]["id"],  # type: ignore[index]
            "entry_type": "plate",
            "plate_number": "TST 9090",
            "reason": "security",
            "description": "Temporary test block",
        },
    )
    assert created.status_code == 201, created.text
    entry_id = created.json()["id"]

    updated = client.patch(
        f"/api/v1/blacklist/{entry_id}",
        headers=admin_headers,
        json={"is_active": False},
    )
    assert updated.status_code == 200
    assert updated.json()["is_active"] is False

    all_entries = client.get(
        "/api/v1/blacklist", headers=admin_headers, params={"page_size": 200}
    )
    assert all_entries.status_code == 200
    assert any(item["id"] == entry_id for item in all_entries.json()["items"])

    active_entries = client.get(
        "/api/v1/blacklist",
        headers=admin_headers,
        params={"page_size": 200, "is_active": "true"},
    )
    assert active_entries.status_code == 200
    assert all(item["id"] != entry_id for item in active_entries.json()["items"])

    deleted = client.delete(f"/api/v1/blacklist/{entry_id}", headers=admin_headers)
    assert deleted.status_code == 200


def test_face_gallery_search_filters_by_resident(
    client: TestClient, admin_headers: dict[str, str], demo: dict[str, object]
) -> None:
    resident = next(
        item
        for item in demo["residents"]  # type: ignore[union-attr]
        if item["full_name"] == "Ahmed Hassan"
    )
    enrolled = client.post(
        "/api/v1/faces/enroll",
        headers=admin_headers,
        files={"file": ("face.png", io.BytesIO(_png_bytes()), "image/png")},
        data={"resident_id": resident["id"]},
    )
    assert enrolled.status_code == 201, enrolled.text
    embedding_id = enrolled.json()["id"]

    matched = client.get(
        "/api/v1/faces",
        headers=admin_headers,
        params={"search": "Ahmed", "page_size": 200},
    )
    assert matched.status_code == 200
    assert any(item["id"] == embedding_id for item in matched.json()["items"])

    missed = client.get(
        "/api/v1/faces",
        headers=admin_headers,
        params={"search": "NoSuchResident", "page_size": 200},
    )
    assert missed.status_code == 200
    assert missed.json()["total"] == 0

    deactivated = client.post(
        f"/api/v1/faces/{embedding_id}/deactivate", headers=admin_headers
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False


def test_security_centre_requires_manager_role(
    client: TestClient, resident_headers: dict[str, str]
) -> None:
    assert (
        client.get("/api/v1/blacklist", headers=resident_headers)
    ).status_code == 403
    me = client.get("/api/v1/residents/me", headers=resident_headers).json()
    faces = client.get("/api/v1/faces", headers=resident_headers)
    assert faces.status_code == 200
    assert all(item["resident_id"] == me["id"] for item in faces.json()["items"])
