from __future__ import annotations

"""Database engine with PostgreSQL → SQLite graceful degradation."""

import logging
from collections.abc import Generator
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

logger = logging.getLogger("sterling.database")

SQLITE_FALLBACK_URL = "sqlite:///./data/sterling.db"

_engine: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker] = None
_using_sqlite: bool = False


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all models."""


def _probe_url(url: str) -> bool:
    """Return True if a short SELECT 1 succeeds against url."""
    if not (url or "").strip():
        return False
    try:
        kwargs = {"pool_pre_ping": True, "future": True}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
        eng = create_engine(url, **kwargs)
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        eng.dispose()
        return True
    except Exception as exc:
        logger.warning("Database probe failed for %s: %s", url.split("@")[-1], exc)
        return False


def _normalize_pg_scheme(url: str) -> str:
    """Coerce a plain Postgres URL to the psycopg v3 driver form.

    Managed hosts (Render, Railway, Heroku, Fly, ...) hand out connection
    strings as ``postgres://`` or ``postgresql://``. SQLAlchemy would then pick
    the default psycopg2 driver, which isn't installed here — only psycopg v3 is.
    Rewrite the scheme to ``postgresql+psycopg://`` while preserving credentials,
    host, port, database, and query string. Any scheme that already names a
    driver (``postgresql+psycopg``, ``postgresql+asyncpg``, ...) or isn't
    Postgres (sqlite) is returned untouched.
    """
    if not url:
        return url
    lowered = url.lower()
    if lowered.startswith("postgresql+") or not lowered.startswith("postgres"):
        return url
    # Split only on the first "://" so passwords containing "://" are safe.
    _, sep, rest = url.partition("://")
    if not sep:
        return url
    return f"postgresql+psycopg://{rest}"


def resolve_database_url() -> str:
    """Prefer DATABASE_URL (Postgres); fall back to local SQLite when unreachable."""
    import os
    if os.getenv("FORCE_SQLITE", "").lower() in ("1", "true", "t", "yes", "y"):
        return SQLITE_FALLBACK_URL

    raw_force = getattr(settings, "force_sqlite", False)
    if raw_force is True or str(raw_force).lower() in ("1", "true", "t", "yes", "y"):
        return SQLITE_FALLBACK_URL

    preferred = _normalize_pg_scheme((settings.database_url or "").strip())
    if preferred.lower().startswith("sqlite"):
        return preferred

    if preferred:
        if _probe_url(preferred):
            return preferred
        # Postgres was explicitly configured but unreachable. Never silently
        # diverge data stores in production — a transient blip must crash-and-restart,
        # not write to a throwaway SQLite file that vanishes when Postgres returns.
        if settings.is_production:
            raise RuntimeError(
                f"Configured PostgreSQL is unreachable and ENVIRONMENT=production; "
                f"refusing to fall back to SQLite ({SQLITE_FALLBACK_URL}). "
                f"Set FORCE_SQLITE=1 to opt in explicitly."
            )
    logger.warning(
        "PostgreSQL unavailable — using SQLite fallback at %s (Docker-free mode)",
        SQLITE_FALLBACK_URL,
    )
    Path("./data").mkdir(parents=True, exist_ok=True)
    return SQLITE_FALLBACK_URL


def create_db_engine(url: Optional[str] = None) -> Engine:
    global _using_sqlite
    db_url = url or resolve_database_url()
    _using_sqlite = db_url.lower().startswith("sqlite")
    kwargs: dict = {"pool_pre_ping": True, "future": True}
    if _using_sqlite:
        Path("./data").mkdir(parents=True, exist_ok=True)
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(db_url, **kwargs)


def init_engine() -> Engine:
    """Create (or recreate) the global engine + session factory."""
    global _engine, _SessionLocal
    if _engine is not None:
        try:
            _engine.dispose()
        except Exception:
            pass
    _engine = create_db_engine()
    _SessionLocal = sessionmaker(
        bind=_engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        init_engine()
    assert _engine is not None
    return _engine


def using_sqlite() -> bool:
    get_engine()
    return _using_sqlite


def ensure_schema() -> None:
    """Create tables. Prefer create_all for SQLite; try Alembic on Postgres."""
    # Import models so their tables register on Base.metadata (side-effect import).
    import app.models

    _ = app.models  # reference to satisfy static analysis; import is for side effects

    eng = get_engine()
    if using_sqlite():
        Base.metadata.create_all(bind=eng)
        logger.info("SQLite schema ready (create_all)")
        return
    try:
        from alembic import command
        from alembic.config import Config

        cfg = Config("alembic.ini")
        command.upgrade(cfg, "head")
        logger.info("Alembic upgrade head complete")
    except Exception as exc:
        if settings.is_production:
            raise RuntimeError(
                f"Alembic migration failed in production: {exc}. "
                f"Refusing to fall back to create_all. "
                f"Fix migrations before deploying."
            ) from exc
        logger.warning("Alembic failed (%s) — falling back to create_all (non-production)", exc)
        Base.metadata.create_all(bind=eng)


# Lazy module-level engine for imports that expect `engine` / `SessionLocal`
engine = None  # type: ignore[assignment]


def __getattr__(name: str):
    if name == "engine":
        return get_engine()
    if name == "SessionLocal":
        get_engine()
        assert _SessionLocal is not None
        return _SessionLocal
    raise AttributeError(name)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a DB session and closes it afterward."""
    get_engine()
    assert _SessionLocal is not None
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()
