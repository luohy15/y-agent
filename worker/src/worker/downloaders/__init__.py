"""Link content downloaders with per-domain routing."""

from worker.downloaders.router import route_and_download

__all__ = ["route_and_download"]
