"""Pipeline lock service."""

from storage.repository import pipeline_lock as pipeline_lock_repo


def try_acquire_lock(action: str, ttl_seconds: int = 840) -> bool:
    return pipeline_lock_repo.try_acquire_lock(action, ttl_seconds=ttl_seconds)


def release_lock(action: str) -> None:
    pipeline_lock_repo.release_lock(action)


def is_locked(action: str, ttl_seconds: int = 840) -> bool:
    return pipeline_lock_repo.is_locked(action, ttl_seconds=ttl_seconds)
