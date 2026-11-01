"""Role-based access control and tenant scoping tests."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

API = "/api/v1"


def test_resident_cannot_manage_compound(
    client: TestClient, resident_headers: dict[str, str]
) -> None:
    assert client.get(f"{API}/residents", headers=resident_headers).status_code == 403
    assert client.get(f"{API}/cameras", headers=resident_headers).status_code == 403
    assert client.get(f"{API}/analytics/dashboard", headers=resident_headers).status_code == 403
    assert client.get(f"{API}/users", headers=resident_headers).status_code == 403
    assert client.get(f"{API}/blacklist", headers=resident_headers).status_code == 403
    assert client.post(
        f"{API}/permits",
        headers=resident_headers,
        json={
            "visitor_id": "00000000-0000-0000-0000-000000000000",
            "host_unit_id": "00000000-0000-0000-0000-000000000000",
            "start_at": "2026-01-01T10:00:00Z",
            "end_at": "2026-01-02T10:00:00Z",
        },
    ).status_code == 403


def test_officer_cannot_manage_users(
    client: TestClient, officer_headers: dict[str, str]
) -> None:
    assert client.get(f"{API}/users", headers=officer_headers).status_code == 403
    assert client.post(
        f"{API}/compounds",
        headers=officer_headers,
        json={"name": "Sneaky Compound", "code": "SNK"},
    ).status_code == 403


def test_user_crud_requires_admin(
    client: TestClient,
    admin_headers: dict[str, str],
    officer_headers: dict[str, str],
    demo: dict[str, Any],
) -> None:
    create = client.post(
        f"{API}/users",
        headers=admin_headers,
        json={
            "email": "rbac.officer@gatevision.app",
            "password": "Rbac@12345",
            "full_name": "RBAC Officer",
            "role": "security_officer",
            "compound_id": demo["compound"]["id"],
        },
    )
    assert create.status_code == 201, create.text
    user_id = create.json()["id"]

    duplicate = client.post(
        f"{API}/users",
        headers=admin_headers,
        json={
            "email": "rbac.officer@gatevision.app",
            "password": "Rbac@12345",
            "full_name": "Duplicate",
            "role": "resident",
        },
    )
    assert duplicate.status_code == 409

    assert client.patch(
        f"{API}/users/{user_id}", headers=officer_headers, json={"full_name": "Nope"}
    ).status_code == 403

    updated = client.patch(
        f"{API}/users/{user_id}", headers=admin_headers, json={"full_name": "Renamed Officer"}
    )
    assert updated.status_code == 200
    assert updated.json()["full_name"] == "Renamed Officer"

    reset = client.post(
        f"{API}/users/{user_id}/reset-password",
        headers=admin_headers,
        json={"new_password": "Reset@12345"},
    )
    assert reset.status_code == 200
    assert client.post(
        f"{API}/auth/login",
        json={"email": "rbac.officer@gatevision.app", "password": "Reset@12345"},
    ).status_code == 200

    assert client.delete(f"{API}/users/{user_id}", headers=admin_headers).status_code == 200
    assert client.post(
        f"{API}/auth/login",
        json={"email": "rbac.officer@gatevision.app", "password": "Reset@12345"},
    ).status_code == 401


def test_admin_cannot_deactivate_self(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    me = client.get(f"{API}/auth/me", headers=admin_headers).json()
    response = client.delete(f"{API}/users/{me['id']}", headers=admin_headers)
    assert response.status_code == 400


def test_resident_scoped_reads(
    client: TestClient, resident_headers: dict[str, str], demo: dict[str, Any]
) -> None:
    profile = client.get(f"{API}/residents/me", headers=resident_headers)
    assert profile.status_code == 200
    profile_body = profile.json()
    assert profile_body["full_name"] == "Ahmed Hassan"

    other = next(r for r in demo["residents"] if r["id"] != profile_body["id"])
    assert client.get(
        f"{API}/residents/{other['id']}", headers=resident_headers
    ).status_code == 403

    vehicles = client.get(f"{API}/vehicles", headers=resident_headers).json()
    assert vehicles["items"]
    assert all(item["resident_id"] == profile_body["id"] for item in vehicles["items"])

    logs = client.get(f"{API}/access-logs", headers=resident_headers).json()
    assert all(
        item["resident_id"] == profile_body["id"]
        or (item["visitor"] is not None and item["visitor"]["status"] != "rejected")
        or item["resident_id"] is None
        for item in logs["items"]
    )

    stranger = client.get(
        f"{API}/vehicles/{next(v['id'] for v in demo['vehicles'] if v['plate_number'] == 'CAI 1122')}",
        headers=resident_headers,
    )
    assert stranger.status_code == 403


def test_tenant_isolation_for_other_compound(
    client: TestClient, admin_headers: dict[str, str], officer_headers: dict[str, str]
) -> None:
    created = client.post(
        f"{API}/compounds",
        headers=admin_headers,
        json={"name": "Second Compound", "code": "SECOND"},
    )
    assert created.status_code == 201, created.text
    compound_id = created.json()["id"]
    gate = client.post(
        f"{API}/gates",
        headers=admin_headers,
        json={"compound_id": compound_id, "name": "Second Gate", "code": "S-IN"},
    )
    assert gate.status_code == 201

    # The officer belongs to the demo compound and must not see or manage another.
    assert client.get(
        f"{API}/gates?compound_id={compound_id}", headers=officer_headers
    ).status_code == 403
    assert client.get(
        f"{API}/gates/{gate.json()['id']}", headers=officer_headers
    ).status_code == 403
    other_compound_read = client.get(
        f"{API}/compounds/{compound_id}", headers=officer_headers
    )
    assert other_compound_read.status_code == 403

    # Cleanup (the new compound has no history so it can be deleted).
    assert client.delete(
        f"{API}/gates/{gate.json()['id']}", headers=admin_headers
    ).status_code == 200
    assert client.delete(
        f"{API}/compounds/{compound_id}", headers=admin_headers
    ).status_code == 200
