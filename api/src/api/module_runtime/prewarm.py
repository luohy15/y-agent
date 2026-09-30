"""Synchronous warmup of the API process before it accepts traffic (todo 3780).

Called from the FastAPI lifespan, so Lambda Web Adapter does not report
ready until it returns. A background thread would freeze with the instance
and then compete with the first request, so this stays on the startup thread.

Fail-open: a missing database, an unset maintainer, or any step error is
logged and swallowed. Once PREWARM_BUDGET_SECONDS has elapsed, later steps
are skipped. A step already running is not cancelled.
"""

import time

from loguru import logger

PREWARM_MODULE_SLUGS = ("chat",)
PREWARM_BUDGET_SECONDS = 1.5


def _ping_db() -> None:
    from sqlalchemy import text

    from storage.database.base import get_db

    with get_db() as session:
        session.execute(text("SELECT 1"))


def _configure_mappers() -> None:
    from sqlalchemy.orm import configure_mappers

    configure_mappers()


def _load_modules() -> None:
    from api.controller.module import default_owner_user_id
    from api.module_runtime import loader

    owner_id = default_owner_user_id()
    if owner_id is None:
        return
    for slug in PREWARM_MODULE_SLUGS:
        loader.load_active_module(owner_id, slug)


def prewarm() -> None:
    steps = (
        ("db", _ping_db),
        ("mappers", _configure_mappers),
        ("modules", _load_modules),
    )
    started = time.perf_counter()
    parts = []
    for name, step in steps:
        if time.perf_counter() - started >= PREWARM_BUDGET_SECONDS:
            break
        began = time.perf_counter()
        try:
            step()
        except Exception as exc:
            parts.append(f"{name}=error")
            logger.warning("module prewarm step {} failed open: {}", name, exc)
            continue
        parts.append(f"{name}={(time.perf_counter() - began) * 1000:.0f}ms")
    logger.info("module prewarm {}", " ".join(parts) if parts else "skipped")
