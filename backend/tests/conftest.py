"""Shared pytest fixtures.

The environment is configured *before* importing the application so the cached
settings point at an isolated SQLite database and a temporary media directory.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from typing import Any

import pytest

TEMP_ROOT = tempfile.mkdtemp(prefix="gatevision-tests-")
os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DEBUG": "false",
        "DATABASE_URL": f"sqlite+aiosqlite:///{TEMP_ROOT}/gatevision.db",
        "AUTO_CREATE_TABLES": "true",
        "SEED_DEMO_DATA": "true",
        "CV_ENABLED": "false",
        "CV_RUNNER_ENABLED": "false",
        "CV_MODE": "mock",
        "REDIS_ENABLED": "false",
        "SECRET_KEY": "test-secret-key-that-is-long-enough-1234567890",
        "MEDIA_ROOT": f"{TEMP_ROOT}/media",
        "LOG_LEVEL": "WARNING",
        "LOG_FORMAT": "text",
        "ACCESS_TOKEN_EXPIRE_MINUTES": "60",
    }
)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

API = "/api/v1"


@pytest.fixture(scope="session")
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def _login(client: TestClient, email: str, password: str) -> dict[str, str]:
    response = client.post(f"{API}/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture(scope="session")
def admin_headers(client: TestClient) -> dict[str, str]:
    return _login(client, "admin@gatevision.app", "Admin@12345")


@pytest.fixture(scope="session")
def officer_headers(client: TestClient) -> dict[str, str]:
    return _login(client, "officer@gatevision.app", "Officer@12345")


@pytest.fixture(scope="session")
def resident_headers(client: TestClient) -> dict[str, str]:
    return _login(client, "ahmed@gatevision.app", "Resident@12345")


@pytest.fixture(scope="session")
def demo(client: TestClient, admin_headers: dict[str, str]) -> dict[str, Any]:
    compounds = client.get(f"{API}/compounds", headers=admin_headers).json()
    compound = compounds["items"][0]
    gates = client.get(f"{API}/gates", headers=admin_headers).json()["items"]
    entry_gate = next(g for g in gates if g["code"] == "GATE-IN")
    exit_gate = next(g for g in gates if g["code"] == "GATE-OUT")
    residents = client.get(f"{API}/residents?page_size=50", headers=admin_headers).json()["items"]
    vehicles = client.get(f"{API}/vehicles?page_size=50", headers=admin_headers).json()["items"]
    permits = client.get(f"{API}/permits", headers=admin_headers).json()["items"]
    visitors = client.get(f"{API}/visitors", headers=admin_headers).json()["items"]
    return {
        "compound": compound,
        "gate": entry_gate,
        "exit_gate": exit_gate,
        "residents": residents,
        "vehicles": vehicles,
        "permits": permits,
        "visitors": visitors,
        "resident_by_name": {r["full_name"]: r for r in residents},
        "vehicle_by_plate": {v["plate_number"]: v for v in vehicles},
    }


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Remove the temporary database/media directory after the run."""
    shutil.rmtree(TEMP_ROOT, ignore_errors=True)
