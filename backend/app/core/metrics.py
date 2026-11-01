"""Prometheus instrumentation for GateVision.

Everything is registered on a private :class:`CollectorRegistry` instead of the
default one: importing the app twice (tests, reloads) must not raise
``Duplicated timeseries``.

The metrics cover the three questions an operator asks during an incident:

* is the API healthy and fast?  -> ``gatevision_http_*``
* what is the gate deciding?   -> ``gatevision_access_decisions_total``
* is the barrier actually opening? -> ``gatevision_barrier_commands_total``
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Iterator

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

REGISTRY = CollectorRegistry(auto_describe=True)

HTTP_REQUESTS = Counter(
    "gatevision_http_requests_total",
    "HTTP requests processed by the API.",
    ["method", "route", "status"],
    registry=REGISTRY,
)
HTTP_DURATION = Histogram(
    "gatevision_http_request_duration_seconds",
    "HTTP request latency.",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    registry=REGISTRY,
)
ACCESS_DECISIONS = Counter(
    "gatevision_access_decisions_total",
    "Access decisions produced by the decision engine.",
    ["decision", "reason_code"],
    registry=REGISTRY,
)
BARRIER_COMMANDS = Counter(
    "gatevision_barrier_commands_total",
    "Barrier commands sent to the hardware actuators.",
    ["driver", "action", "accepted"],
    registry=REGISTRY,
)
VISION_RESULTS = Counter(
    "gatevision_vision_results_total",
    "Vision pipeline invocations grouped by outcome.",
    ["outcome"],
    registry=REGISTRY,
)
ENROLLMENTS = Counter(
    "gatevision_face_enrollments_total",
    "Face enrollment attempts.",
    ["result"],
    registry=REGISTRY,
)

CV_ENGINE_READY = Gauge(
    "gatevision_cv_engine_ready",
    "1 when the vision engine finished loading its models.",
    registry=REGISTRY,
)
CV_MODE = Gauge(
    "gatevision_cv_mode_real",
    "1 when CV_MODE=real, 0 for the mock pipeline.",
    registry=REGISTRY,
)
FACE_GALLERY_ENTRIES = Gauge(
    "gatevision_face_gallery_entries",
    "Active face embeddings available for matching.",
    registry=REGISTRY,
)
BARRIER_DRIVER_INFO = Gauge(
    "gatevision_barrier_driver",
    "Active barrier driver per compound (value is always 1).",
    ["compound", "driver"],
    registry=REGISTRY,
)
MAINTENANCE_RUNS = Counter(
    "gatevision_maintenance_runs_total",
    "Maintenance cycles that completed.",
    ["outcome"],
    registry=REGISTRY,
)
MAINTENANCE_PURGED = Counter(
    "gatevision_maintenance_purged_total",
    "Rows and files deleted by retention jobs.",
    ["kind"],
    registry=REGISTRY,
)
MAINTENANCE_LAST_SUCCESS = Gauge(
    "gatevision_maintenance_last_success_timestamp_seconds",
    "Unix timestamp of the last successful maintenance cycle.",
    registry=REGISTRY,
)
APP_INFO = Gauge(
    "gatevision_app_info",
    "Static build information (value is always 1).",
    ["version", "environment", "cv_mode"],
    registry=REGISTRY,
)


def describe_route(template: str) -> str:
    """Return a low-cardinality label for a request path.

    Path parameters are already collapsed by FastAPI's router template, but the
    middleware also sees unmatched paths; collapse anything that looks like an
    id or a UUID file name to keep cardinality bounded.
    """

    parts: list[str] = []
    for segment in template.strip("/").split("/"):
        if not segment:
            continue
        if segment.isdigit() or (len(segment) >= 20 and segment.count("-") >= 3):
            parts.append("{param}")
        elif "." in segment and len(segment) > 12:
            parts.append("{file}")
        else:
            parts.append(segment)
    return "/" + "/".join(parts)


@contextmanager
def track_http(method: str, route: str) -> Iterator[None]:
    """Context-manager form of :func:`observe_latency`."""
    started = time.perf_counter()
    try:
        yield
    finally:
        observe_latency(method, route, time.perf_counter() - started)


def observe_latency(method: str, route: str, seconds: float) -> None:
    """Record one request duration (seconds)."""
    HTTP_DURATION.labels(method=method, route=route).observe(max(0.0, seconds))


def observe_http(method: str, route: str, status: int) -> None:
    """Count one finished request."""
    HTTP_REQUESTS.labels(method=method, route=route, status=str(status)).inc()


def record_decision(decision: str, reason_code: str) -> None:
    ACCESS_DECISIONS.labels(decision=decision, reason_code=reason_code).inc()


def record_barrier_command(driver: str, action: str, accepted: bool) -> None:
    BARRIER_COMMANDS.labels(
        driver=driver, action=action, accepted="true" if accepted else "false"
    ).inc()


def record_vision_result(outcome: str) -> None:
    VISION_RESULTS.labels(outcome=outcome).inc()


def record_enrollment(result: str) -> None:
    ENROLLMENTS.labels(result=result).inc()


def set_engine_state(*, ready: bool, mode: str, gallery_entries: int | None = None) -> None:
    CV_ENGINE_READY.set(1 if ready else 0)
    CV_MODE.set(1 if mode == "real" else 0)
    if gallery_entries is not None:
        FACE_GALLERY_ENTRIES.set(gallery_entries)


def set_barrier_driver(compound: object, driver: str) -> None:
    BARRIER_DRIVER_INFO.labels(compound=str(compound), driver=driver).set(1)


def record_maintenance(
    *, purged: dict[str, int], success: bool, finished_at: float
) -> None:
    MAINTENANCE_RUNS.labels(outcome="success" if success else "failure").inc()
    for kind, count in purged.items():
        if count > 0:
            MAINTENANCE_PURGED.labels(kind=kind).inc(count)
    if success:
        MAINTENANCE_LAST_SUCCESS.set(finished_at)


def set_app_info(version: str, environment: str, cv_mode: str) -> None:
    APP_INFO.labels(version=version, environment=environment, cv_mode=cv_mode).set(1)


def render_metrics() -> tuple[bytes, str]:
    """Return the Prometheus exposition payload and content type."""
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


__all__ = [
    "ACCESS_DECISIONS",
    "APP_INFO",
    "BARRIER_COMMANDS",
    "BARRIER_DRIVER_INFO",
    "CV_ENGINE_READY",
    "CV_MODE",
    "ENROLLMENTS",
    "FACE_GALLERY_ENTRIES",
    "HTTP_DURATION",
    "HTTP_REQUESTS",
    "MAINTENANCE_LAST_SUCCESS",
    "MAINTENANCE_PURGED",
    "MAINTENANCE_RUNS",
    "REGISTRY",
    "VISION_RESULTS",
    "describe_route",
    "observe_http",
    "observe_latency",
    "record_barrier_command",
    "record_decision",
    "record_enrollment",
    "record_maintenance",
    "record_vision_result",
    "render_metrics",
    "set_app_info",
    "set_barrier_driver",
    "set_engine_state",
    "track_http",
]
