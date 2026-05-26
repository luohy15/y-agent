import sys

import click

from yagent.api_client import api_request


def looks_like_url(value: str) -> bool:
    return value.startswith(("http://", "https://"))


def normalize_url(value: str) -> str:
    if value.startswith(("http://", "https://")):
        return value
    return "https://" + value


def resolve_url_ref(value: str, *, exit_on_missing: bool = True) -> dict | None:
    url = normalize_url(value)
    resolved = api_request("GET", "/api/link/resolve", params={"url": url}).json()
    if resolved.get("found"):
        resolved["url"] = url
        return resolved
    if exit_on_missing:
        click.echo(f"Link not found for URL: {url}", err=True)
        sys.exit(1)
    return None
