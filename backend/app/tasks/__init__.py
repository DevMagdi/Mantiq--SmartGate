"""Scheduled maintenance tasks.

GateVision keeps background work in two places:

* :mod:`app.services.maintenance` holds the idempotent business jobs (permit and
  visitor expiry) so they can also be triggered from the API or the CLI.
* This package wires those jobs into a scheduler and adds the retention jobs
  (old detections, access logs and snapshot files) that keep the database and
  the media volume from growing without bound.

Run a single cycle with ``python -m app.tasks --once`` (cron/Kubernetes Job) or
let the API process run the loop via ``MAINTENANCE_ENABLED=true``.
"""

from __future__ import annotations

from app.tasks.maintenance import (
    maintenance_loop,
    prune_media,
    purge_expired_records,
    run_once,
)

__all__ = ["maintenance_loop", "prune_media", "purge_expired_records", "run_once"]
