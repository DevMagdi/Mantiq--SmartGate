"""Scripted scenarios powering the offline demo pipeline.

These constants are shared by two consumers:

* :mod:`app.services.seed_service` creates matching residents, vehicles,
  permits and blacklist entries so that every scenario produces a realistic
  access decision.
* :mod:`app.cv.sources` renders synthetic camera frames for each scenario.

The demo pipeline is intentionally deterministic: it lets evaluators see the
full detection → decision → audit pipeline without any camera hardware or model
downloads.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DemoScenario:
    """One scripted gate event rendered by the demo camera."""

    key: str
    plate_text: str | None
    face_key: str | None
    face_in_car: bool
    description: str
    expected_decision: str


DEMO_SCENARIOS: tuple[DemoScenario, ...] = (
    DemoScenario(
        key="resident-entry",
        plate_text="CAI 4821",
        face_key=None,
        face_in_car=False,
        description="Registered resident vehicle entering",
        expected_decision="allow",
    ),
    DemoScenario(
        key="visitor-permit",
        plate_text="GZ 5520",
        face_key=None,
        face_in_car=False,
        description="Visitor vehicle with an active temporary permit",
        expected_decision="allow",
    ),
    DemoScenario(
        key="unknown-vehicle",
        plate_text="ALX 3344",
        face_key=None,
        face_in_car=False,
        description="Unregistered plate at the gate",
        expected_decision="unknown",
    ),
    DemoScenario(
        key="blacklisted-plate",
        plate_text="SUZ 7788",
        face_key=None,
        face_in_car=False,
        description="Blacklisted vehicle approaching the barrier",
        expected_decision="deny",
    ),
    DemoScenario(
        key="resident-pedestrian",
        plate_text=None,
        face_key="resident:ahmed",
        face_in_car=False,
        description="Resident walking in through the pedestrian lane",
        expected_decision="allow",
    ),
    DemoScenario(
        key="blocked-person",
        plate_text=None,
        face_key="person:blocked",
        face_in_car=False,
        description="Blacklisted person detected by face recognition",
        expected_decision="deny",
    ),
    DemoScenario(
        key="known-face-unknown-car",
        plate_text="CAI 9999",
        face_key="resident:mona",
        face_in_car=True,
        description="Recognised resident driving an unregistered vehicle",
        expected_decision="review",
    ),
    DemoScenario(
        key="suspended-resident",
        plate_text="CAI 1122",
        face_key=None,
        face_in_car=False,
        description="Vehicle of a resident whose access is suspended",
        expected_decision="deny",
    ),
)

#: Demo identities referenced by the seed service and the scene renderer.
DEMO_FACE_KEYS: dict[str, str] = {
    "resident:ahmed": "Ahmed Hassan",
    "resident:mona": "Mona Adel",
    "person:blocked": "Zaki Mahmoud",
}


def scenario_by_key(key: str) -> DemoScenario:
    """Return a scenario by key (raises ``KeyError`` when unknown)."""
    for scenario in DEMO_SCENARIOS:
        if scenario.key == key:
            return scenario
    raise KeyError(f"Unknown demo scenario: {key}")


def mock_meta_for_scenario(key: str, width: int, height: int) -> dict[str, object]:
    """Build mock detection metadata for an uploaded image (demo mode only).

    The mock engines cannot read pixels, so the demo verification endpoint can
    script what a camera would have seen. The bounding boxes are expressed as
    fractions of the uploaded image so any resolution works.
    """
    scenario = scenario_by_key(key)
    meta: dict[str, object] = {
        "scenario": scenario.key,
        "description": scenario.description,
        "plate_text": scenario.plate_text,
        "plate_confidence": 0.93,
        "face_bboxes": [],
        "face_keys": [],
    }
    if scenario.plate_text:
        meta["plate_bbox"] = {
            "x1": int(width * 0.36),
            "y1": int(height * 0.62),
            "x2": int(width * 0.64),
            "y2": int(height * 0.72),
        }
    if scenario.face_key:
        if scenario.face_in_car:
            box = {
                "x1": int(width * 0.46),
                "y1": int(height * 0.40),
                "x2": int(width * 0.54),
                "y2": int(height * 0.51),
            }
        else:
            box = {
                "x1": int(width * 0.44),
                "y1": int(height * 0.24),
                "x2": int(width * 0.56),
                "y2": int(height * 0.40),
            }
        meta["face_bboxes"] = [box]
        meta["face_keys"] = [scenario.face_key]
    return meta
