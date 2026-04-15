"""Database setup for PostgreSQL."""

import os
from contextlib import contextmanager
from typing import Optional

from storage.global_config import load_global_config

load_global_config()

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, Session
from storage.entity.base import Base


_engine: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker] = None


def _get_engine_kwargs(url: str) -> dict:
    if url.startswith("postgresql://") or url.startswith("postgresql+psycopg://"):
        return {
            "pool_pre_ping": True,
            "pool_size": 5,
            "max_overflow": 10,
            "pool_recycle": 3600,
            "pool_timeout": 5,
            "echo": False,
        }
    return {"echo": False}


def init_db(database_url: str):
    """Initialize the database engine and session factory."""
    global _engine, _SessionLocal

    if _engine is not None:
        return

    engine_kwargs = _get_engine_kwargs(database_url)

    _engine = create_engine(database_url, **engine_kwargs)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)


def init_tables():
    """Create all database tables defined in the entity models."""
    if _engine is None:
        database_url = os.getenv("DATABASE_URL_DEV", os.getenv("DATABASE_URL"))
        if database_url:
            init_db(database_url)
        else:
            raise RuntimeError("Database not initialized. Set DATABASE_URL_DEV or DATABASE_URL, or call init_db() first.")

    # Import all entities to register them with Base
    import storage.entity.user  # noqa: F401
    import storage.entity.bot_config  # noqa: F401
    import storage.entity.vm_config  # noqa: F401
    import storage.entity.chat  # noqa: F401
    import storage.entity.todo  # noqa: F401
    import storage.entity.calendar_event  # noqa: F401
    import storage.entity.link  # noqa: F401
    import storage.entity.email  # noqa: F401
    import storage.entity.dev_worktree  # noqa: F401
    import storage.entity.tg_topic  # noqa: F401
    import storage.entity.trace_share  # noqa: F401
    import storage.entity.link_todo_relation  # noqa: F401
    import storage.entity.note  # noqa: F401
    import storage.entity.note_todo_relation  # noqa: F401

    Base.metadata.create_all(bind=_engine)


@contextmanager
def get_db() -> Session:
    """Context manager that yields a SQLAlchemy session."""
    if _SessionLocal is None:
        # Auto-initialize from DATABASE_URL env var
        database_url = os.getenv("DATABASE_URL_DEV", os.getenv("DATABASE_URL"))
        if database_url:
            init_db(database_url)
        else:
            raise RuntimeError("Database not initialized. Set DATABASE_URL_DEV or DATABASE_URL, or call init_db() first.")
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
