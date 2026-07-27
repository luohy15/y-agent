import json

import click

from yagent.api_client import api_request


@click.command("pending")
@click.option("--limit", "-l", default=50, help="Max eligible messages per run")
@click.option(
    "--since",
    default=None,
    help="Lower bound as unix ms or ISO 8601 (overrides watermark / bootstrap)",
)
def english_pending(limit, since):
    """List eligible unscanned messages as JSON (machine interface for the skill)."""
    params = {"limit": limit}
    if since is not None:
        # Accept plain unix ms integers; ISO strings are converted client-side.
        try:
            params["since"] = int(since)
        except ValueError:
            from datetime import datetime

            s = since
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
            params["since"] = int(dt.timestamp() * 1000)

    resp = api_request("GET", "/api/english/pending", params=params)
    click.echo(json.dumps(resp.json(), ensure_ascii=False))
