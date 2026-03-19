"""Dev worktree service."""

from typing import List, Optional
from storage.dto.dev_worktree import DevWorktree, DevWorktreeHistoryEntry
from storage.repository import dev_worktree as wt_repo
from storage.util import generate_id, get_utc_iso8601_timestamp, get_unix_timestamp


def list_worktrees(user_id: int, status: Optional[str] = None, limit: int = 50) -> List[DevWorktree]:
    return wt_repo.list_worktrees(user_id, status=status, limit=limit)


def get_worktree(user_id: int, worktree_id: str) -> Optional[DevWorktree]:
    return wt_repo.get_worktree(user_id, worktree_id)


def get_worktree_by_name(user_id: int, name: str) -> Optional[DevWorktree]:
    return wt_repo.get_worktree_by_name(user_id, name)


def create_worktree(
    user_id: int,
    name: str,
    project_path: str,
    worktree_path: str,
    branch: str,
) -> DevWorktree:
    wt = DevWorktree(
        worktree_id=generate_id(),
        name=name,
        project_path=project_path,
        worktree_path=worktree_path,
        branch=branch,
        status="active",
        history=[DevWorktreeHistoryEntry(
            timestamp=get_utc_iso8601_timestamp(),
            unix_timestamp=get_unix_timestamp(),
            action="created",
        )],
    )
    return wt_repo.save_worktree(user_id, wt)


def update_worktree(user_id: int, worktree_id: str, **fields) -> Optional[DevWorktree]:
    wt = wt_repo.get_worktree(user_id, worktree_id)
    if not wt:
        return None
    changed = []
    for key, value in fields.items():
        if hasattr(wt, key) and getattr(wt, key) != value:
            setattr(wt, key, value)
            changed.append(key)
    if changed:
        history = wt.history or []
        history.append(DevWorktreeHistoryEntry(
            timestamp=get_utc_iso8601_timestamp(),
            unix_timestamp=get_unix_timestamp(),
            action="updated",
            note=f"changed: {', '.join(f'{k}={getattr(wt, k)!r}' for k in changed)}",
        ))
        wt.history = history
        return wt_repo.save_worktree(user_id, wt)
    return wt


def remove_worktree(user_id: int, worktree_id: str) -> Optional[DevWorktree]:
    wt = wt_repo.get_worktree(user_id, worktree_id)
    if not wt:
        return None
    wt.status = "removed"
    history = wt.history or []
    history.append(DevWorktreeHistoryEntry(
        timestamp=get_utc_iso8601_timestamp(),
        unix_timestamp=get_unix_timestamp(),
        action="removed",
    ))
    wt.history = history
    return wt_repo.save_worktree(user_id, wt)


def remove_worktree_by_name(user_id: int, name: str) -> Optional[DevWorktree]:
    wt = wt_repo.get_worktree_by_name(user_id, name)
    if not wt:
        return None
    return remove_worktree(user_id, wt.worktree_id)
