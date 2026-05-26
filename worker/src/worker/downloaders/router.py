"""Route a URL to the SSH downloader.

Always SSH to the user's VM and call `y link fetch --json` (single source of truth).
See `pages/plan-1965-fetch-link-dry.md` for the rationale.
"""

from worker.downloaders import ssh as ssh_dl


async def route_and_download(
    user_id: int,
    url: str,
    timeout: int = 300,
    link_id: str | None = None,
    activity_id: str | None = None,
) -> dict:
    """Dispatch every URL through SSH → `y link fetch --json` on the user's VM.

    Returns `{status, title, content, method_used, error}`.
    """
    return await ssh_dl.download(user_id, url, timeout=timeout, link_id=link_id, activity_id=activity_id)
