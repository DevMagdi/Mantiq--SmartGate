"""Health, authentication and account security tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

API = "/api/v1"


def test_liveness_and_readiness(client: TestClient) -> None:
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    ready = client.get("/health/ready")
    assert ready.status_code == 200
    body = ready.json()
    assert body["database"] is True
    assert body["cv_mode"] == "mock"


def test_login_and_me(client: TestClient) -> None:
    response = client.post(
        f"{API}/auth/login",
        json={"email": "admin@gatevision.app", "password": "Admin@12345"},
    )
    assert response.status_code == 200
    token = response.json()
    assert token["token_type"] == "bearer"
    assert token["user"]["role"] == "admin"
    assert token["expires_in"] > 0

    me = client.get(
        f"{API}/auth/me", headers={"Authorization": f"Bearer {token['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["email"] == "admin@gatevision.app"


def test_invalid_credentials(client: TestClient) -> None:
    bad_password = client.post(
        f"{API}/auth/login", json={"email": "admin@gatevision.app", "password": "wrong"}
    )
    assert bad_password.status_code == 401
    assert bad_password.json()["error"]["code"] == "invalid_credentials"

    unknown = client.post(
        f"{API}/auth/login", json={"email": "ghost@gatevision.app", "password": "whatever"}
    )
    assert unknown.status_code == 401


def test_missing_and_malformed_tokens(client: TestClient) -> None:
    assert client.get(f"{API}/vehicles").status_code == 401
    bad = client.get(f"{API}/vehicles", headers={"Authorization": "Bearer not-a-token"})
    assert bad.status_code == 401
    assert bad.json()["error"]["code"] == "invalid_token"


def test_refresh_token_rotation(client: TestClient) -> None:
    login = client.post(
        f"{API}/auth/login",
        json={"email": "officer@gatevision.app", "password": "Officer@12345"},
    ).json()
    refreshed = client.post(
        f"{API}/auth/refresh", json={"refresh_token": login["refresh_token"]}
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"] != login["access_token"]

    misuse = client.post(
        f"{API}/auth/refresh", json={"refresh_token": login["access_token"]}
    )
    assert misuse.status_code == 401
    assert misuse.json()["error"]["code"] == "invalid_token_type"


def test_change_password_and_restore(
    client: TestClient, officer_headers: dict[str, str]
) -> None:
    change = client.post(
        f"{API}/auth/change-password",
        headers=officer_headers,
        json={"current_password": "Officer@12345", "new_password": "NewOfficer@12345"},
    )
    assert change.status_code == 200

    relogin = client.post(
        f"{API}/auth/login",
        json={"email": "officer@gatevision.app", "password": "NewOfficer@12345"},
    )
    assert relogin.status_code == 200
    new_headers = {"Authorization": f"Bearer {relogin.json()['access_token']}"}

    weak = client.post(
        f"{API}/auth/change-password",
        headers=new_headers,
        json={"current_password": "NewOfficer@12345", "new_password": "short"},
    )
    assert weak.status_code == 422

    wrong_current = client.post(
        f"{API}/auth/change-password",
        headers=new_headers,
        json={"current_password": "bad", "new_password": "Another@12345"},
    )
    assert wrong_current.status_code == 400

    restore = client.post(
        f"{API}/auth/change-password",
        headers=new_headers,
        json={"current_password": "NewOfficer@12345", "new_password": "Officer@12345"},
    )
    assert restore.status_code == 200


def test_logout(client: TestClient, officer_headers: dict[str, str]) -> None:
    response = client.post(f"{API}/auth/logout", headers=officer_headers)
    assert response.status_code == 200
    assert "Signed out" in response.json()["message"]
