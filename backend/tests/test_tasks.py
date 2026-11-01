"""Maintenance and retention task tests."""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.db.session import session_scope
from app.models.access import AccessLog
from app.models.enums import AccessDecision, AccessDirection, AccessMethod
from app.services.maintenance import maintenance_service
from app.tasks.maintenance import prune_media, purge_expired_records, run_once

API = "/api/v1"


def test_prune_media_respects_retention(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    old = tmp_path / "plates" / "2025" / "old.jpg"
    fresh = tmp_path / "plates" / "2026" / "fresh.jpg"
    old.parent.mkdir(parents=True)
    fresh.parent.mkdir(parents=True)
    old.write_bytes(b"old")
    fresh.write_bytes(b"fresh")
    old_stamp = (now - timedelta(days=40)).timestamp()
    os.utime(old, (old_stamp, old_stamp))
    (tmp_path / ".gitkeep").write_text("")

    removed = asyncio.run(prune_media(30, tmp_path, now=now))
    assert removed == 1
    assert not old.exists()
    assert fresh.exists()
    assert (tmp_path / ".gitkeep").exists()

    assert asyncio.run(prune_media(30, tmp_path, now=now)) == 0
    assert asyncio.run(prune_media(0, tmp_path, now=now)) == 0


def test_purge_expired_records_removes_only_old_rows(
    client: TestClient, demo: dict[str, Any]
) -> None:
    async def scenario() -> tuple[dict[str, int], bool]:
        async with session_scope() as session:
            ancient = AccessLog(
                compound_id=uuid.UUID(demo["compound"]["id"]),
                gate_id=uuid.UUID(demo["gate"]["id"]),
                direction=AccessDirection.ENTRY,
                occurred_at=datetime.now(UTC) - timedelta(days=400),
                decision=AccessDecision.ALLOW,
                reason_code="retention_test",
                reason="Synthetic row used to test retention",
                access_method=AccessMethod.MANUAL,
                gate_opened=True,
            )
            session.add(ancient)
            await session.commit()
            ancient_id = ancient.id

        async with session_scope() as session:
            counts = await purge_expired_records(session, retention_days=365)

        async with session_scope() as session:
            still_there = await session.get(AccessLog, ancient_id) is not None
        return counts, still_there

    results, still_there = asyncio.run(scenario())
    assert results["access_logs_purged"] >= 1
    assert still_there is False

    dashboard = client.get(f"{API}/analytics/dashboard", headers=_admin(client))
    assert dashboard.status_code == 200
    assert dashboard.json()["overview"]["entries_today"] >= 1


def test_maintenance_expires_stale_visitors(
    client: TestClient, admin_headers: dict[str, str], demo: dict[str, Any]
) -> None:
    stale = client.post(
        f"{API}/visitors",
        headers=admin_headers,
        json={
            "compound_id": demo["compound"]["id"],
            "full_name": "Forgotten Visitor",
            "phone": "+20 100 111 2222",
            "host_unit_id": demo["residents"][0]["unit_id"],
            "expected_arrival": (datetime.now(UTC) - timedelta(days=3)).isoformat(),
        },
    )
    assert stale.status_code == 201, stale.text

    stats = asyncio.run(run_once())
    assert stats["visitors_expired"] >= 1
    assert stats["media_files_pruned"] >= 0
    assert "permits_updated" in stats

    refreshed = client.get(
        f"{API}/visitors/{stale.json()['id']}", headers=admin_headers
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["status"] == "expired"


def test_maintenance_service_is_idempotent(client: TestClient) -> None:
    async def cycle() -> tuple[dict[str, int], dict[str, int]]:
        first = await maintenance_service.run_once()
        second = await maintenance_service.run_once()
        return first, second

    first, second = asyncio.run(cycle())
    assert first["visitors_expired"] >= 0
    assert second["permits_updated"] == 0
    assert second["visitors_expired"] == 0


def _admin(client: TestClient) -> dict[str, str]:
    token = client.post(
        f"{API}/auth/login",
        json={"email": "admin@gatevision.app", "password": "Admin@12345"},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
