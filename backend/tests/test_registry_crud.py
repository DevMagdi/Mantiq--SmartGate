"""Entity CRUD and validation tests for the core registry."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

API = "/api/v1"


def test_compound_crud(client: TestClient, admin_headers: dict[str, str]) -> None:
    created = client.post(
        f"{API}/compounds",
        headers=admin_headers,
        json={
            "name": "Palm Residences",
            "code": "PALM",
            "address": "New Cairo",
            "city": "Cairo",
            "timezone": "Africa/Cairo",
            "unit_count": 120,
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["code"] == "PALM"

    duplicate = client.post(
        f"{API}/compounds", headers=admin_headers, json={"name": "Palm 2", "code": "PALM"}
    )
    assert duplicate.status_code == 409

    updated = client.patch(
        f"{API}/compounds/{body['id']}",
        headers=admin_headers,
        json={"city": "Sheikh Zayed", "is_active": False},
    )
    assert updated.status_code == 200
    assert updated.json()["city"] == "Sheikh Zayed"
    assert updated.json()["is_active"] is False

    assert client.delete(f"{API}/compounds/{body['id']}", headers=admin_headers).status_code == 200
    assert client.get(f"{API}/compounds/{body['id']}", headers=admin_headers).status_code == 404


def test_gate_and_camera_crud(
    client: TestClient, admin_headers: dict[str, str], demo: dict[str, Any]
) -> None:
    compound_id = demo["compound"]["id"]
    gate = client.post(
        f"{API}/gates",
        headers=admin_headers,
        json={
            "compound_id": compound_id,
            "name": "Service Gate",
            "code": "SVC-TEST",
            "direction": "bidirectional",
            "location": "North perimeter",
        },
    )
    assert gate.status_code == 201, gate.text
    gate_id = gate.json()["id"]
    assert gate.json()["status"] == "online"

    camera = client.post(
        f"{API}/cameras",
        headers=admin_headers,
        json={
            "gate_id": gate_id,
            "name": "Service Cam",
            "source_type": "rtsp",
            "source_url": "rtsp://192.168.1.20:554/stream1",
            "type": "entry",
        },
    )
    assert camera.status_code == 201, camera.text
    camera_id = camera.json()["id"]

    toggled = client.post(
        f"{API}/cameras/{camera_id}/toggle?active=false", headers=admin_headers
    )
    assert toggled.status_code == 200
    assert toggled.json()["status"] == "disabled"

    invalid_camera = client.post(
        f"{API}/cameras",
        headers=admin_headers,
        json={"gate_id": gate_id, "name": "Bad Cam", "source_type": "usb", "source_url": ""},
    )
    assert invalid_camera.status_code == 422

    gate_update = client.patch(
        f"{API}/gates/{gate_id}", headers=admin_headers, json={"status": "maintenance"}
    )
    assert gate_update.status_code == 200
    assert gate_update.json()["status"] == "maintenance"

    assert client.delete(f"{API}/cameras/{camera_id}", headers=admin_headers).status_code == 200
    assert client.delete(f"{API}/gates/{gate_id}", headers=admin_headers).status_code == 200


def test_unit_resident_vehicle_flow(
    client: TestClient, admin_headers: dict[str, str], demo: dict[str, Any]
) -> None:
    compound_id = demo["compound"]["id"]
    unit = client.post(
        f"{API}/compounds/{compound_id}/units",
        headers=admin_headers,
        json={
            "building": "D",
            "unit_number": "901",
            "floor": 9,
            "bedrooms": 3,
            "area_sqm": 180,
            "status": "occupied",
        },
    )
    assert unit.status_code == 201, unit.text
    unit_id = unit.json()["id"]
    assert unit.json()["label"] == "D-901"

    duplicate_unit = client.post(
        f"{API}/compounds/{compound_id}/units",
        headers=admin_headers,
        json={"building": "D", "unit_number": "901"},
    )
    assert duplicate_unit.status_code == 409

    resident = client.post(
        f"{API}/residents",
        headers=admin_headers,
        json={
            "compound_id": compound_id,
            "unit_id": unit_id,
            "full_name": "Mariam Fathy",
            "national_id": "29001011234567",
            "phone": "+20 100 555 1212",
            "email": "mariam@example.com",
            "role_in_unit": "owner",
            "is_primary": True,
        },
    )
    assert resident.status_code == 201, resident.text
    resident_id = resident.json()["id"]
    assert resident.json()["unit"]["id"] == unit_id

    duplicate_nid = client.post(
        f"{API}/residents",
        headers=admin_headers,
        json={
            "compound_id": compound_id,
            "unit_id": unit_id,
            "full_name": "Impostor",
            "national_id": "29001011234567",
        },
    )
    assert duplicate_nid.status_code == 409

    vehicle = client.post(
        f"{API}/vehicles",
        headers=admin_headers,
        json={
            "compound_id": compound_id,
            "resident_id": resident_id,
            "plate_number": "CAI 7700",
            "make": "Toyota",
            "model": "Corolla",
            "color": "White",
            "year": 2022,
            "type": "car",
        },
    )
    assert vehicle.status_code == 201, vehicle.text
    assert vehicle.json()["plate_normalized"] == "CAI7700"
    vehicle_id = vehicle.json()["id"]

    duplicate_plate = client.post(
        f"{API}/vehicles",
        headers=admin_headers,
        json={"compound_id": compound_id, "plate_number": "cai-7700"},
    )
    assert duplicate_plate.status_code == 409

    suspended = client.patch(
        f"{API}/vehicles/{vehicle_id}", headers=admin_headers, json={"status": "suspended"}
    )
    assert suspended.status_code == 200
    assert suspended.json()["status"] == "suspended"

    blocked_delete = client.delete(f"{API}/residents/{resident_id}", headers=admin_headers)
    assert blocked_delete.status_code == 409

    assert client.delete(f"{API}/vehicles/{vehicle_id}", headers=admin_headers).status_code == 200
    assert client.delete(f"{API}/residents/{resident_id}", headers=admin_headers).status_code == 200
    assert client.delete(
        f"{API}/compounds/{compound_id}/units/{unit_id}", headers=admin_headers
    ).status_code == 200


def test_blacklist_and_face_gallery(
    client: TestClient, admin_headers: dict[str, str], demo: dict[str, Any]
) -> None:
    compound_id = demo["compound"]["id"]
    entry = client.post(
        f"{API}/blacklist",
        headers=admin_headers,
        json={
            "compound_id": compound_id,
            "entry_type": "plate",
            "plate_number": "NO 1234",
            "reason": "security",
            "description": "Repeat trespassing",
        },
    )
    assert entry.status_code == 201, entry.text
    assert entry.json()["plate_normalized"] == "NO1234"
    entry_id = entry.json()["id"]

    assert client.post(
        f"{API}/blacklist",
        headers=admin_headers,
        json={
            "compound_id": compound_id,
            "entry_type": "plate",
            "plate_number": "no-1234",
        },
    ).status_code == 409

    assert client.get(f"{API}/blacklist?entry_type=plate", headers=admin_headers).json()["total"] >= 2
    deactivated = client.patch(
        f"{API}/blacklist/{entry_id}", headers=admin_headers, json={"is_active": False}
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False
    assert client.delete(f"{API}/blacklist/{entry_id}", headers=admin_headers).status_code == 200

    faces = client.get(f"{API}/faces", headers=admin_headers).json()
    assert faces["total"] >= 4
    assert all(item["dimension"] == 512 for item in faces["items"])
    face_id = faces["items"][0]["id"]
    assert client.delete(f"{API}/faces/{face_id}", headers=admin_headers).status_code == 200
