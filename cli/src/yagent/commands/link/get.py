import sys

import click
import httpx

from yagent.api_client import api_request
from ._resolve import looks_like_url, resolve_url_ref


def _fetch_content(id_value):
    """Try activity_id first, then link_id. Returns dict or exits."""
    if looks_like_url(id_value):
        resolved = resolve_url_ref(id_value)
        activity_id = resolved.get("activity_id") if resolved else None
        link_id = resolved.get("link_id") if resolved else None
        if activity_id:
            return api_request("GET", "/api/link/content", params={"activity_id": activity_id}).json()
        if link_id:
            return api_request("GET", "/api/link/content", params={"link_id": link_id}).json()

    try:
        resp = api_request("GET", "/api/link/content", params={"activity_id": id_value})
        return resp.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            pass
        else:
            raise
    try:
        resp = api_request("GET", "/api/link/content", params={"link_id": id_value})
        return resp.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            click.echo(f"Link not found: {id_value}", err=True)
            sys.exit(1)
        raise


@click.command('get')
@click.argument('id')
@click.option('--output', '-o', default=None, help='Output file path (default: stdout)')
def link_get(id, output):
    """Get link details and content by activity_id, link_id, or URL."""
    link = _fetch_content(id)

    click.echo(f"Link ID:   {link.get('link_id', '-')}")
    click.echo(f"URL:       {link.get('base_url') or link.get('url', '-')}")
    click.echo(f"Title:     {link.get('title') or '-'}")
    click.echo(f"Status:    {link.get('download_status') or '-'}")
    click.echo(f"Content:   {link.get('content_key') or '-'}")

    content = link.get('content')
    if not content:
        click.echo("\nNo content available")
        return

    if output:
        with open(output, 'w') as f:
            f.write(content)
        click.echo(f"\nContent written to {output}")
    else:
        click.echo(f"\n--- Content ({len(content)} chars) ---")
        click.echo(content)
