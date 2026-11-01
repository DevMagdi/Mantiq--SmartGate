"""Allow ``python -m app.tasks`` to run maintenance jobs."""

from __future__ import annotations

from app.tasks.maintenance import main

if __name__ == "__main__":
    raise SystemExit(main())
