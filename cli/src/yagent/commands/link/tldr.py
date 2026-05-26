import sys

import click
import httpx

from yagent.api_client import api_request


def _post_tldr(id_value: str, force: bool) -> dict:
    try:
        return api_request("POST", "/api/link/tldr", json={"link_id": id_value, "force": force}).json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code != 404:
            raise
    try:
        return api_request("POST", "/api/link/tldr", json={"activity_id": id_value, "force": force}).json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            click.echo(f"Link not found: {id_value}", err=True)
            sys.exit(1)
        raise


@click.command('tldr')
@click.argument('id')
@click.option('--force', is_flag=True, help='Regenerate even if a summary already exists.')
def link_tldr(id, force):
    """Generate or fetch TLDR summary by link_id or activity_id."""
    result = _post_tldr(id, force)
    if result.get("skipped"):
        click.echo("summary already exists, use --force to regenerate")
    summary = result.get("summary")
    if summary:
        click.echo(summary)
    else:
        click.echo(result.get("summary_content_key") or "")
