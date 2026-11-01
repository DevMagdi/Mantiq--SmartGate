"""Visitor requests and temporary permit lifecycle tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient

API = "/api/v1"


def _window(hours: int = 4) -> dict[str, str]:
    start = datetime.now(UTC) - timedelta(minutes=10)
    return {
        "start_at": start.isoformat(),
        "end_at": (start + timedelta(hours=hours)).isoformat(),
    }


def test_visitor_request_approval_flow(
    client: TestClient,
    resident_headers: dict[str, str],
    officer_headers: dict[str, str],
    demo: dict[str, Any],
) -> None:
    profile = client.get(f"{API}/residents/me", headers=resident_headers).json()
    unit_id = profile["unit_id"]

    email = datetime.now(UTC).timestamp()
    request_payload = {
        "compound_id": demo["compound"]["id"],
        "full_name": f"Visitor {email:.0f}",
        "phone": "+20 101 777 4545",
        "email": "visitor@example.com",
        "purpose": "Family visit",
        "host_unit_id": unit_id,
        "expected_arrival": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    }
    created = client.post(f"{API}/visitors", headers=resident_headers, json=request_payload)
    assert created.status_code == 201, created.text
    visitor = created.json()
    assert visitor["status"] == "pending"
    assert visitor["host_unit"]["id"] == unit_id

    assert client.get(
        f"{API}/visitors?status=pending", headers=resident_headers
    ).json()["total"] >= 1

    approved = client.post(f"{API}/visitors/{visitor['id']}/approve", headers=officer_headers)
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    rejected_source = client.post(
        f"{API}/visitors", headers=resident_headers, json={**request_payload, "full_name": "Rejected Person"}
    ).json()
    rejected = client.post(
        f"{API}/visitors/{rejected_source['id']}/reject",
        headers=officer_headers,
        json={"reason": "Not expected by the resident"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"

    # A rejected visitor cannot receive a permit.
    forbidden_permit = client.post(
        f"{API}/permits",
        headers=officer_headers,
        json={
            "visitor_id": rejected_source["id"],
            "host_unit_id": unit_id,
            **_window(),
        },
    )
    assert forbidden_permit.status_code == 400


def test_permit_lifecycle_and_checkin(
    client: TestClient,
    officer_headers: dict[str, str],
    demo: dict[str, Any],
) -> None:
    approved = next(v for v in demo["visitors"] if v["status"] in {"approved", "checked_in"})
    unit_id = approved["host_unit"]["id"]
    permit = client.post(
        f"{API}/permits",
        headers=officer_headers,
        json={
            "visitor_id": approved["id"],
            "host_unit_id": unit_id,
            "vehicle_plate": "DK 4321",
            "max_entries": 2,
            "notes": "Weekend stay",
            **_window(hours=6),
        },
    )
    assert permit.status_code == 201, permit.text
    body = permit.json()
    assert body["status"] == "active"
    assert body["permit_code"].startswith("PMT-")
    assert body["vehicle_plate"] == "DK 4321"

    invalid_window = client.post(
        f"{API}/permits",
        headers=officer_headers,
        json={
            "visitor_id": approved["id"],
            "host_unit_id": unit_id,
            "start_at": datetime.now(UTC).isoformat(),
            "end_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        },
    )
    assert invalid_window.status_code == 422

    checked_in = client.post(
        f"{API}/visitors/{approved['id']}/check-in", headers=officer_headers
    )
    assert checked_in.status_code == 200
    assert checked_in.json()["status"] == "checked_in"
    assert checked_in.json()["actual_arrival"] is not None

    checked_out = client.post(
        f"{API}/visitors/{approved['id']}/check-out", headers=officer_headers
    )
    assert checked_out.status_code == 200
    assert checked_out.json()["status"] == "checked_out"
    assert checked_out.json()["actual_departure"] is not None

    revoked = client.post(
        f"{API}/permits/{body['id']}/revoke",
        headers=officer_headers,
        json={"reason": "Permit replaced"},
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"


def test_expired_permit_is_marked(
    client: TestClient,
    admin_headers: dict[str, str],
    demo: dict[str, Any],
) -> None:
    visitor = demo["visitors"][0]
    start = datetime.now(UTC) - timedelta(days=2)
    permit = client.post(
        f"{API}/permits",
        headers=admin_headers,
        json={
            "visitor_id": visitor["id"],
            "host_unit_id": visitor["host_unit"]["id"],
            "start_at": start.isoformat(),
            "end_at": (start + timedelta(hours=2)).isoformat(),
        },
    )
    assert permit.status_code in {201, 400}
    if permit.status_code == 201:
        listed = client.get(
            f"{API}/permits/{permit.json()['id']}", headers=admin_headers
        ).json()
        assert listed["status"] == "expired"


def test_visitor_photo_upload(
    client: TestClient, officer_headers: dict[str, str], demo: dict[str, Any]
) -> None:
    visitor = demo["visitors"][0]
    response = client.post(
        f"{API}/visitors/{visitor['id']}/photo",
        headers=officer_headers,
        files={"file": ("visitor.jpg", b"\xff\xd8\xff\xe0invalid-jpeg", "image/jpeg")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] in {"invalid_image", "bad_request"}
