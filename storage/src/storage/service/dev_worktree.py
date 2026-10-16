"""Dev worktree service."""

from typing import List, Optional
from storage.dto.dev_worktree import DevWorktree, DevWorktreeHistoryEntry
from storage.repository import dev_worktree as wt_repo
from storage.util import generate_id, get_utc_iso8601_timestamp, get_unix_timestamp

# Omitted limit for anything other than the active registry. Active + omitted
# is unbounded so a long active set cannot be truncated (todo 3938 / 3941).
_LIST_LIMIT_DEFAULT = 50


class DevWorktreeRequestError(ValueError):
    """Caller-visible worktree request rejection. status_code is the HTTP status."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        super().__init__(detail)


def resolve_list_limit(status: Optional[str], limit: Optional[int]) -> Optional[int]:
    """One limit policy for the host route and the module capability.

    None means unbounded. An omitted limit is unbounded only for status=active;
    every other omitted limit stays at 50. An explicit limit must be a positive
    integer. Zero and negative are rejected here, not coerced.
    """
    if limit is None:
        return None if status == "active" else _LIST_LIMIT_DEFAULT
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise DevWorktreeRequestError(422, "limit must be a positive integer")
    return limit


def list_worktrees(user_id: int, status: Optional[str] = None, limit: Optional[int] = None) -> List[DevWorktree]:
    return wt_repo.list_worktrees(
        user_id, status=status, limit=resolve_list_limit(status, limit)
    )


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
    todo_id: Optional[str] = None,
) -> DevWorktree:
    wt = DevWorktree(
        worktree_id=generate_id(),
        name=name,
        project_path=project_path,
        worktree_path=worktree_path,
        branch=branch,
        status="active",
        todo_id=todo_id,
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
