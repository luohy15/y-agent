"""Pipeline lock service."""

from datetime import datetime

from storage.repository import pipeline_lock as pipeline_lock_repo


def try_acquire_lock(action: str, ttl_seconds: int = 840) -> bool:
    return pipeline_lock_repo.try_acquire_lock(action, ttl_seconds=ttl_seconds)


def release_lock(action: str) -> None:
    pipeline_lock_repo.release_lock(action)


def set_marker(
    action: str, name: str, value: datetime, *, overwrite: bool = True
) -> None:
    pipeline_lock_repo.set_marker(action, name, value, overwrite=overwrite)


def get_marker(action: str, name: str) -> datetime | None:
    return pipeline_lock_repo.get_marker(action, name)


def record_success(action: str) -> None:
    pipeline_lock_repo.record_success(action)


def last_success_at(action: str) -> datetime | None:
    return pipeline_lock_repo.last_success_at(action)


def is_locked(action: str, ttl_seconds: int = 840) -> bool:
    return pipeline_lock_repo.is_locked(action, ttl_seconds=ttl_seconds)


def try_acquire_exclusive_lock(action: str, ttl_seconds: int) -> bool:
    return pipeline_lock_repo.try_acquire_exclusive_lock(action, ttl_seconds=ttl_seconds)
