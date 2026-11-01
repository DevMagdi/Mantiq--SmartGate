"""Egyptian plate rules, per-compound policy and enrollment quality gates."""

from __future__ import annotations

import struct
import zlib

import pytest
from starlette.testclient import TestClient

from app.cv.plate_rules import (
    best_plate_match,
    describe_plate,
    format_plate_latin,
    has_arabic,
    merge_plate_readings,
    parse_plate,
    plate_similarity,
    plate_variants,
    quality_score,
    transliterate_plate,
)
from app.services.compound_policy import (
    CompoundPolicy,
    SECRET_PLACEHOLDER,
    mask_secrets_in_settings,
)

API = "/api/v1"


# --------------------------------------------------------------------------- #
# Plate rules
# --------------------------------------------------------------------------- #


def test_arabic_plates_are_transliterated_for_matching() -> None:
    assert transliterate_plate("ب ج ١٢٣٤") == "BG1234"
    assert transliterate_plate("ق ١٢٣٤") == "Q1234"
    assert has_arabic("بج 1234") is True
    assert has_arabic("BC 1234") is False
    assert format_plate_latin("ب ج ١٢٣٤") == "BG 1234"


def test_parse_plate_detects_layout_and_groups() -> None:
    letters_first = parse_plate("CAI 4821")
    assert letters_first.letters == "CAI"
    assert letters_first.digits == "4821"
    assert letters_first.style == "letters-first"
    assert letters_first.is_valid

    digits_first = parse_plate("4821 ABC")
    assert digits_first.style == "digits-first"
    assert digits_first.letters == "ABC"

    arabic = parse_plate("أ ب ج ١٢٣٤")
    assert arabic.latin == "ABG1234"
    assert arabic.letters == "ABG"
    assert arabic.digits == "1234"


def test_variants_cover_arabic_swapped_halves_and_ocr_confusions() -> None:
    variants = plate_variants("CAI 4821")
    assert "CAI4821" in variants
    assert "4821CAI" in variants  # camera read the halves in the other order
    assert len(variants) <= 32

    arabic_variants = plate_variants("ب ج ١٢٣٤")
    assert "بج1234" in arabic_variants  # canonical form is kept
    assert "BG1234" in arabic_variants  # transliterated form matches registrations

    assert plate_variants(None) == set()


def test_plate_similarity_and_suggestions() -> None:
    assert plate_similarity("CAI 4821", "CAI 4821") == 1.0
    assert plate_similarity("CAI 4821", "CAI 4822") > 0.8
    assert plate_similarity("CAI 4821", "ALX 9999") < 0.5
    assert best_plate_match("CAI 4822", ["CAI 4821", "ALX 9999"]) is not None
    assert best_plate_match("ZZZ 0000", ["CAI 4821"], threshold=0.95) is None


def test_quality_score_penalises_implausible_plates() -> None:
    plausible = quality_score(0.9, parse_plate("CAI 4821"))
    implausible = quality_score(0.9, parse_plate("ABCDEFGH"))
    assert plausible > implausible
    assert 0 <= implausible <= 100


def test_plate_describe_and_majority_vote() -> None:
    description = describe_plate("CAI 4821")
    assert description["valid"] is True
    assert description["variants"] and description["variants"] > 0
    assert merge_plate_readings(["CAI 4821", "CAI 4821", "CAI 4827"]) == "CAI4821"
    assert merge_plate_readings([]) is None


# --------------------------------------------------------------------------- #
# Compound policy
# --------------------------------------------------------------------------- #


def test_policy_parses_legacy_and_nested_settings() -> None:
    policy = CompoundPolicy.from_settings(
        {
            "auto_open_barrier": False,
            "allow_face_only_entry": False,
            "vision": {"face_similarity_threshold": 0.62},
        }
    )
    assert policy.access.auto_open_barrier is False
    assert policy.access.allow_face_only_entry is False
    assert policy.vision.face_similarity_threshold == pytest.approx(0.62)
    assert policy.barrier.driver == "simulator"


def test_policy_clamps_dangerous_values() -> None:
    policy = CompoundPolicy.from_settings(
        {
            "vision": {
                "face_similarity_threshold": 5.0,
                "ocr_min_confidence": -1,
                "max_embeddings_per_resident": 99,
            },
            "access": {"unknown_vehicle_decision": "allow", "exit_grace_minutes": -5},
            "barrier": {"driver": "rocket"},
        }
    )
    assert policy.vision.face_similarity_threshold <= 0.85
    assert policy.vision.ocr_min_confidence >= 0.05
    assert policy.vision.max_embeddings_per_resident <= 10
    # "allow" is never a valid fallback for unknown vehicles.
    assert policy.access.unknown_vehicle_decision.value in {"unknown", "review", "deny"}
    assert policy.access.exit_grace_minutes >= 0
    assert policy.barrier.driver == "simulator"


def test_legacy_webhook_url_selects_webhook_driver() -> None:
    policy = CompoundPolicy.from_settings({"gate_webhook_url": "https://relay.local/open"})
    assert policy.barrier.driver == "webhook"
    assert policy.barrier.webhook.url == "https://relay.local/open"


def test_secrets_are_masked_in_responses() -> None:
    document = {
        "barrier": {
            "driver": "mqtt",
            "mqtt": {"password": "super-secret"},
            "webhook": {"secret": "hmac-key"},
        }
    }
    masked = mask_secrets_in_settings(document)
    assert masked["barrier"]["mqtt"]["password"] == SECRET_PLACEHOLDER
    assert masked["barrier"]["webhook"]["secret"] == SECRET_PLACEHOLDER
    # The source document is untouched.
    assert document["barrier"]["mqtt"]["password"] == "super-secret"


# --------------------------------------------------------------------------- #
# API: compound settings + policy effects
# --------------------------------------------------------------------------- #


def _png(width: int = 640, height: int = 640, *, textured: bool = True) -> bytes:
    """Synthetic PNG; ``textured`` adds detail so the blur gate passes."""
    if not textured:
        raw = b"".join(b"\x00" + bytes((150, 160, 170)) * width for _ in range(height))
    else:
        import cv2
        import numpy as np

        rng = np.random.default_rng(7)
        image = rng.integers(60, 200, size=(height, width, 3), dtype=np.uint8)
        cv2.ellipse(
            image,
            (width // 2, height // 2),
            (width // 5, height // 4),
            0,
            0,
            360,
            (180, 170, 160),
            -1,
        )
        cv2.circle(image, (width // 2 - 20, height // 2 - 10), 6, (30, 30, 30), -1)
        cv2.circle(image, (width // 2 + 20, height // 2 - 10), 6, (30, 30, 30), -1)
        ok, buffer = cv2.imencode(".png", image)
        assert ok
        return buffer.tobytes()

    def chunk(tag: bytes, data: bytes) -> bytes:
        payload = tag + data
        return struct.pack(">I", len(data)) + payload + struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )


def test_compound_settings_roundtrip_and_rbac(
    client: TestClient,
    admin_headers: dict[str, str],
    officer_headers: dict[str, str],
    demo: dict[str, object],
) -> None:
    compound_id = demo["compound"]["id"]  # type: ignore[index]

    current = client.get(f"{API}/compounds/{compound_id}/settings", headers=admin_headers)
    assert current.status_code == 200
    body = current.json()
    assert body["effective"]["vision"]["face_similarity_threshold"] > 0
    assert body["defaults"]["barrier"]["driver"] == "simulator"

    updated = client.patch(
        f"{API}/compounds/{compound_id}/settings",
        headers=admin_headers,
        json={
            "vision": {"face_similarity_threshold": 0.55, "max_embeddings_per_resident": 2},
            "access": {"unknown_vehicle_decision": "review"},
            "barrier": {
                "driver": "mqtt",
                "mqtt": {"host": "broker.local", "password": "secret-value", "simulate": True},
            },
        },
    )
    assert updated.status_code == 200, updated.text
    effective = updated.json()["effective"]
    assert effective["vision"]["face_similarity_threshold"] == pytest.approx(0.55)
    assert effective["access"]["unknown_vehicle_decision"] == "review"
    assert effective["barrier"]["driver"] == "mqtt"
    assert effective["barrier"]["mqtt"]["password"] == SECRET_PLACEHOLDER

    listing = client.get(f"{API}/compounds", headers=admin_headers)
    listed = next(item for item in listing.json()["items"] if item["id"] == compound_id)
    assert listed["settings"]["barrier"]["mqtt"]["password"] != "secret-value"

    forbidden = client.patch(
        f"{API}/compounds/{compound_id}/settings",
        headers=officer_headers,
        json={"vision": {"face_similarity_threshold": 0.3}},
    )
    assert forbidden.status_code == 403

    invalid = client.patch(
        f"{API}/compounds/{compound_id}/settings",
        headers=admin_headers,
        json={"vision": {"face_similarity_threshold": 3.5}},
    )
    assert invalid.status_code == 422

    # Restore the demo policy for the rest of the suite.
    client.patch(
        f"{API}/compounds/{compound_id}/settings",
        headers=admin_headers,
        json={
            "access": {"unknown_vehicle_decision": "unknown"},
            "barrier": {"driver": "simulator"},
        },
    )


def test_unknown_vehicle_policy_changes_the_decision(
    client: TestClient,
    admin_headers: dict[str, str],
    demo: dict[str, object],
) -> None:
    gate = demo["gate"]  # type: ignore[index]
    compound_id = demo["compound"]["id"]  # type: ignore[index]

    def analyze() -> dict[str, object]:
        response = client.post(
            f"{API}/cv/analyze",
            headers=admin_headers,
            files={"file": ("frame.png", _png(), "image/png")},
            data={"gate_id": gate["id"], "demo_scenario": "unknown-vehicle"},
        )
        assert response.status_code == 200, response.text
        return response.json()

    assert analyze()["decision"] == "unknown"

    client.patch(
        f"{API}/compounds/{compound_id}/settings",
        headers=admin_headers,
        json={"access": {"unknown_vehicle_decision": "review"}},
    )
    assert analyze()["decision"] == "review"

    client.patch(
        f"{API}/compounds/{compound_id}/settings",
        headers=admin_headers,
        json={"access": {"unknown_vehicle_decision": "deny"}},
    )
    assert analyze()["decision"] == "deny"

    client.patch(
        f"{API}/compounds/{compound_id}/settings",
        headers=admin_headers,
        json={"access": {"unknown_vehicle_decision": "unknown"}},
    )
    assert analyze()["decision"] == "unknown"


def test_require_face_for_vehicle_forces_review(
    client: TestClient,
    admin_headers: dict[str, str],
    demo: dict[str, object],
) -> None:
    gate = demo["gate"]  # type: ignore[index]
    compound_id = demo["compound"]["id"]  # type: ignore[index]

    baseline = client.post(
        f"{API}/cv/analyze",
        headers=admin_headers,
        files={"file": ("frame.png", _png(), "image/png")},
        data={"gate_id": gate["id"], "demo_scenario": "resident-entry"},
    )
    assert baseline.status_code == 200
    assert baseline.json()["decision"] == "allow"

    client.patch(
        f"{API}/compounds/{compound_id}/settings",
        headers=admin_headers,
        json={"access": {"require_face_for_vehicle": True}},
    )
    strict = client.post(
        f"{API}/cv/analyze",
        headers=admin_headers,
        files={"file": ("frame.png", _png(), "image/png")},
        data={"gate_id": gate["id"], "demo_scenario": "resident-entry"},
    )
    assert strict.status_code == 200
    assert strict.json()["decision"] == "review"
    assert strict.json()["reason_code"] == "face_required_missing"

    client.patch(
        f"{API}/compounds/{compound_id}/settings",
        headers=admin_headers,
        json={"access": {"require_face_for_vehicle": False}},
    )


# --------------------------------------------------------------------------- #
# API: enrollment quality
# --------------------------------------------------------------------------- #


def test_quality_check_rejects_a_tiny_photo(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    response = client.post(
        f"{API}/faces/quality-check",
        headers=admin_headers,
        files={"file": ("tiny.png", _png(90, 90, textured=False), "image/png")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["passed"] is False
    assert any(issue["code"] == "low_resolution" for issue in body["issues"])
    assert body["thresholds"]["face_min_resolution"] >= 80


def test_quality_check_accepts_a_clear_photo_and_enrolls(
    client: TestClient, admin_headers: dict[str, str], demo: dict[str, object]
) -> None:
    resident = next(
        item for item in demo["residents"] if item["full_name"] == "Karim Nabil"  # type: ignore[index]
    )
    check = client.post(
        f"{API}/faces/quality-check",
        headers=admin_headers,
        data={"resident_id": resident["id"]},
        files={"file": ("photo.png", _png(640, 640), "image/png")},
    )
    assert check.status_code == 200
    assert check.json()["face_count"] == 1

    enrolled = client.post(
        f"{API}/faces/enroll",
        headers=admin_headers,
        data={"resident_id": resident["id"], "overwrite": "true"},
        files={"file": ("photo.png", _png(640, 640), "image/png")},
    )
    assert enrolled.status_code == 201, enrolled.text
    assert enrolled.json()["quality"] > 0


def test_enrollment_is_rejected_when_quality_is_too_low(
    client: TestClient, admin_headers: dict[str, str], demo: dict[str, object]
) -> None:
    resident = next(
        item for item in demo["residents"] if item["full_name"] == "Karim Nabil"  # type: ignore[index]
    )
    response = client.post(
        f"{API}/faces/enroll",
        headers=admin_headers,
        data={"resident_id": resident["id"]},
        files={"file": ("tiny.png", _png(96, 96, textured=False), "image/png")},
    )
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "enrollment_rejected"
    assert body["error"]["details"]["passed"] is False


def test_gallery_prune_keeps_the_best_embeddings(
    client: TestClient, admin_headers: dict[str, str], demo: dict[str, object]
) -> None:
    compound_id = demo["compound"]["id"]  # type: ignore[index]
    dry_run = client.post(
        f"{API}/faces/prune",
        headers=admin_headers,
        json={"compound_id": compound_id, "max_per_resident": 1, "dry_run": True},
    )
    assert dry_run.status_code == 200, dry_run.text
    assert "would deactivate" in dry_run.json()["message"]

    applied = client.post(
        f"{API}/faces/prune",
        headers=admin_headers,
        json={"compound_id": compound_id, "max_per_resident": 2},
    )
    assert applied.status_code == 200
    assert "deactivated" in applied.json()["message"]
