"""Access log filtering, manual operations, exports and analytics tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

API = "/api/v1"


def test_manual_entry_links_registered_vehicle(
    client: TestClient, officer_headers: dict[str, str], demo: dict[str, Any]
) -> None:
    vehicle = demo["vehicle_by_plate"]["CAI 4821"]
    start = datetime.now(UTC) - timedelta(seconds=1)
    response = client.post(
        f"{API}/access-logs/manual",
        headers=officer_headers,
        json={
            "gate_id": demo["gate"]["id"],
            "decision": "allow",
            "direction": "entry",
            "plate_number": "CAI-4821",
            "reason": "System outage - officer verified the resident",
            "notes": "Barrier opened manually",
        },
    )
    assert response.status_code == 201, response.text
    log = response.json()
    assert log["access_method"] == "manual"
    assert log["decision"] == "allow"
    assert log["gate_opened"] is True
    assert log["vehicle_id"] == vehicle["id"]
    assert log["resident_id"] == vehicle["resident_id"]
    assert log["plate_number"] == "CAI 4821"
    assert datetime.fromisoformat(log["occurred_at"].replace("Z", "+00:00")) >= start


def test_manual_entry_with_unknown_plate(
    client: TestClient, officer_headers: dict[str, str], demo: dict[str, Any]
) -> None:
    response = client.post(
        f"{API}/access-logs/manual",
        headers=officer_headers,
        json={
            "gate_id": demo["gate"]["id"],
            "decision": "deny",
            "plate_number": "QQ 0000",
            "reason": "Unregistered vehicle refused entry",
        },
    )
    assert response.status_code == 201
    log = response.json()
    assert log["vehicle_id"] is None
    assert log["decision"] == "deny"
    assert log["gate_opened"] is False


def test_access_log_filters(
    client: TestClient, officer_headers: dict[str, str], demo: dict[str, Any]
) -> None:
    denied = client.get(
        f"{API}/access-logs?decision=deny&page_size=100", headers=officer_headers
    ).json()
    assert denied["total"] >= 1
    assert all(item["decision"] == "deny" for item in denied["items"])

    entries = client.get(
        f"{API}/access-logs?direction=entry&page_size=5", headers=officer_headers
    ).json()
    assert all(item["direction"] == "entry" for item in entries["items"])

    plate = client.get(
        f"{API}/access-logs?plate=4821", headers=officer_headers
    ).json()
    assert plate["total"] >= 1
    assert all("4821" in (item["plate_number"] or "").replace(" ", "") for item in plate["items"])

    overridden = client.get(
        f"{API}/access-logs?overridden=true", headers=officer_headers
    ).json()
    assert overridden["total"] >= 1
    assert all(item["is_overridden"] for item in overridden["items"])

    reviews = client.get(
        f"{API}/access-logs?requires_review=true", headers=officer_headers
    ).json()
    assert all(item["decision"] == "review" for item in reviews["items"])

    gate_filtered = client.get(
        f"{API}/access-logs?gate_id={demo['exit_gate']['id']}", headers=officer_headers
    ).json()
    assert all(item["gate_id"] == demo["exit_gate"]["id"] for item in gate_filtered["items"])

    future = datetime.now(UTC) + timedelta(days=1)
    empty = client.get(
        f"{API}/access-logs", headers=officer_headers, params={"start": future.isoformat()}
    ).json()
    assert empty["total"] == 0

    page_two = client.get(
        f"{API}/access-logs?page=2&page_size=4", headers=officer_headers
    ).json()
    assert page_two["page"] == 2
    assert page_two["page_size"] == 4
    assert page_two["pages"] >= 2
    assert len(page_two["items"]) <= 4
    assert {item["id"] for item in page_two["items"]}.isdisjoint(
        {item["id"] for item in client.get(
            f"{API}/access-logs?page=1&page_size=4", headers=officer_headers
        ).json()["items"]}
    )

    sorted_desc = client.get(
        f"{API}/access-logs?sort_by=occurred_at&sort_dir=desc&page_size=10",
        headers=officer_headers,
    ).json()["items"]
    timestamps = [
        datetime.fromisoformat(item["occurred_at"].replace("Z", "+00:00")) for item in sorted_desc
    ]
    assert timestamps == sorted(timestamps, reverse=True)


def test_detections_endpoint(
    client: TestClient, officer_headers: dict[str, str], demo: dict[str, Any]
) -> None:
    listing = client.get(f"{API}/detections?page_size=10", headers=officer_headers)
    assert listing.status_code == 200
    body = listing.json()
    assert body["total"] >= 1
    assert body["items"][0]["vision_engine"]

    denied = client.get(
        f"{API}/detections?decision=deny", headers=officer_headers
    ).json()
    assert all(item["decision"] == "deny" for item in denied["items"])

    plate = client.get(f"{API}/detections?plate=4821", headers=officer_headers).json()
    assert plate["total"] >= 1

    detail = client.get(
        f"{API}/detections/{body['items'][0]['id']}", headers=officer_headers
    )
    assert detail.status_code == 200
    assert detail.json()["id"] == body["items"][0]["id"]

    missing = client.get(
        f"{API}/detections/00000000-0000-0000-0000-000000000000", headers=officer_headers
    )
    assert missing.status_code == 404


@pytest.mark.parametrize("fmt", ["csv", "xlsx"])
def test_export_formats(
    client: TestClient,
    officer_headers: dict[str, str],
    fmt: str,
) -> None:
    response = client.get(f"{API}/access-logs/export?format={fmt}", headers=officer_headers)
    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    assert "attachment" in disposition
    assert disposition.endswith(f'.{fmt}"')
    if fmt == "csv":
        assert response.headers["content-type"].startswith("text/csv")
        text = response.content.decode("utf-8-sig")
        header = text.splitlines()[0]
        for column in ("Plate", "Decision", "Gate", "Direction", "Occurred"):
            assert column in header
        assert len(text.splitlines()) > 1
    else:
        assert response.content[:2] == b"PK"
        assert len(response.content) > 2000


def test_export_respects_filters(
    client: TestClient, officer_headers: dict[str, str]
) -> None:
    response = client.get(
        f"{API}/access-logs/export?format=csv&decision=deny", headers=officer_headers
    )
    assert response.status_code == 200
    lines = response.content.decode("utf-8-sig").strip().splitlines()
    assert len(lines) >= 2
    assert "deny" in response.content.decode("utf-8-sig").lower()

    invalid = client.get(
        f"{API}/access-logs/export?format=pdf", headers=officer_headers
    )
    assert invalid.status_code == 422


def test_resident_export_is_scoped(
    client: TestClient, resident_headers: dict[str, str], demo: dict[str, Any]
) -> None:
    profile = client.get(f"{API}/residents/me", headers=resident_headers).json()
    response = client.get(
        f"{API}/access-logs/export?format=csv", headers=resident_headers
    )
    assert response.status_code == 200
    text = response.content.decode("utf-8-sig")
    # The resident export must not leak records of unrelated gate activity.
    for vehicle in demo["vehicles"]:
        if vehicle["resident_id"] != profile["id"] and vehicle["plate_number"] in text:
            pytest.fail(f"Leaked another resident's vehicle {vehicle['plate_number']}")


def test_dashboard_and_analytics(
    client: TestClient, officer_headers: dict[str, str]
) -> None:
    dashboard = client.get(f"{API}/analytics/dashboard", headers=officer_headers)
    assert dashboard.status_code == 200
    body = dashboard.json()
    overview = body["overview"]
    assert overview["entries_today"] >= 1
    assert overview["residents_total"] >= 6
    assert overview["vehicles_total"] >= 7
    assert overview["cameras_total"] == 3
    assert 0.0 <= overview["face_match_rate"] <= 1.0
    assert len(body["peak_hours"]) == 24
    assert len(body["trend"]) == 7
    assert body["trend"][-1]["total"] >= 1
    assert body["decision_breakdown"]
    assert body["recent_access"]
    assert body["recent_detections"]
    assert all(gate["gate_code"] for gate in body["gate_performance"])
    assert 0 < len(body["heatmap"]) <= 7 * 24
    assert all(0 <= cell["day_of_week"] <= 6 and 0 <= cell["hour"] <= 23 for cell in body["heatmap"])

    overview_only = client.get(f"{API}/analytics/overview", headers=officer_headers).json()
    assert overview_only["entries_today"] == overview["entries_today"]

    trend = client.get(
        f"{API}/analytics/trend?days=14&direction=entry", headers=officer_headers
    )
    assert trend.status_code == 200
    assert len(trend.json()) == 14
    assert all(isinstance(point["total"], int) for point in trend.json())

    occupancy = client.get(f"{API}/analytics/occupancy", headers=officer_headers)
    assert occupancy.status_code == 200
    occ = occupancy.json()
    assert occ["inside_now"] >= 0
    assert occ["net_change"] == occ["entries_today"] - occ["exits_today"]
    assert len(occ["by_gate"]) == 3

    breakdown = client.get(
        f"{API}/analytics/blacklist-breakdown", headers=officer_headers
    )
    assert breakdown.status_code == 200
    assert "plate" in breakdown.json()


def test_access_log_detail_permissions(
    client: TestClient,
    resident_headers: dict[str, str],
    officer_headers: dict[str, str],
) -> None:
    profile = client.get(f"{API}/residents/me", headers=resident_headers).json()
    own = client.get(
        f"{API}/access-logs?resident_id={profile['id']}", headers=officer_headers
    ).json()["items"]
    assert own
    assert client.get(
        f"{API}/access-logs/{own[0]['id']}", headers=resident_headers
    ).status_code == 200

    other = next(
        item
        for item in client.get(
            f"{API}/access-logs?page_size=100", headers=officer_headers
        ).json()["items"]
        if item["resident_id"] not in (None, profile["id"])
        and item["visitor_id"] is None
    )
    forbidden = client.get(
        f"{API}/access-logs/{other['id']}", headers=resident_headers
    )
    assert forbidden.status_code == 403
