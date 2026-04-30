"""Route a URL to the SSH downloader.

Always SSH to the user's VM and call `y fetch get --json` (single source of truth).
See `pages/plan-1965-fetch-link-dry.md` for the rationale.
"""

from worker.downloaders import ssh as ssh_dl


async def route_and_download(
    user_id: int,
    url: str,
    timeout: int = 300,
) -> dict:
    """Dispatch every URL through SSH → `y fetch get --json` on the user's VM.

    Returns `{status, title, content, method_used, error}`.
    """
    return await ssh_dl.download(user_id, url, timeout=timeout)
