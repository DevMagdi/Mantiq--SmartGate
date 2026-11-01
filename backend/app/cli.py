"""GateVision command line utilities.

Usage::

    python -m app.cli seed                # create demo data
    python -m app.cli create-admin ...    # bootstrap an administrator
    python -m app.cli expire-permits      # run maintenance once
    python -m app.cli check               # verify database connectivity
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import select, text

from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.core.security import hash_password
from app.db.session import dispose_engine, get_engine, session_scope
from app.models.user import User
from app.models.enums import UserRole

logger = get_logger("gatevision.cli")


async def _create_schema() -> None:
    from app.models import Base

    async with get_engine().begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    logger.info("Schema created/updated from ORM metadata")


async def _seed(args: argparse.Namespace) -> int:
    from app.services.seed_service import seed_demo_data

    if args.create_tables:
        await _create_schema()
    stats = await seed_demo_data(with_history=not args.no_history)
    logger.info("Seed result: %s", stats)
    return 0


async def _create_admin(args: argparse.Namespace) -> int:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.db.session import get_session_factory

    if args.create_tables:
        await _create_schema()
    factory = get_session_factory()
    async with factory() as session:
        assert isinstance(session, AsyncSession)
        existing = await session.scalar(select(User).where(User.email == args.email.lower()))
        if existing is not None:
            existing.hashed_password = hash_password(args.password)
            existing.role = UserRole.ADMIN
            existing.is_active = True
            await session.commit()
            logger.info("Admin password rotated for %s", existing.email)
            return 0
        admin = User(
            email=args.email.lower(),
            hashed_password=hash_password(args.password),
            full_name=args.name,
            role=UserRole.ADMIN,
            is_active=True,
        )
        session.add(admin)
        await session.commit()
        logger.info("Administrator created: %s", admin.email)
        return 0


async def _expire_permits() -> int:
    from app.services.maintenance import maintenance_service

    stats = await maintenance_service.run_once()
    logger.info("Maintenance result: %s", stats)
    return 0


async def _check() -> int:
    try:
        async with get_engine().connect() as connection:
            await connection.execute(text("SELECT 1"))
        async with session_scope() as session:
            counts = {}
            for table in ("users", "compounds", "gates", "vehicles", "access_logs"):
                result = await session.execute(text(f"SELECT COUNT(*) FROM {table}"))
                counts[table] = int(result.scalar_one())
        logger.info("Database OK — %s", counts)
        return 0
    except Exception as exc:
        logger.error("Database check failed: %s", exc)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gatevision", description="GateVision CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    seed = sub.add_parser("seed", help="Seed demo data (idempotent)")
    seed.add_argument("--no-history", action="store_true", help="Skip historical access logs")
    seed.add_argument(
        "--create-tables", action="store_true", help="Create tables from ORM metadata first"
    )
    seed.set_defaults(func=_seed)

    admin = sub.add_parser("create-admin", help="Create or reset an administrator account")
    admin.add_argument("--email", default=settings.SEED_ADMIN_EMAIL)
    admin.add_argument("--password", default=settings.SEED_ADMIN_PASSWORD)
    admin.add_argument("--name", default=settings.SEED_ADMIN_NAME)
    admin.add_argument("--create-tables", action="store_true")
    admin.set_defaults(func=_create_admin)

    expire = sub.add_parser("expire-permits", help="Run permit/visitor expiry once")
    expire.set_defaults(func=lambda _args: _expire_permits())

    check = sub.add_parser("check", help="Check database connectivity and row counts")
    check.set_defaults(func=lambda _args: _check())
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging(settings.LOG_LEVEL, "text")
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return asyncio.run(args.func(args))
    finally:
        asyncio.run(dispose_engine())


if __name__ == "__main__":
    sys.exit(main())
