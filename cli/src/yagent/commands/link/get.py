import os
import sys

import click
import httpx

from yagent.api_client import api_request


CONTENT_DIR = os.path.join(os.path.expanduser(os.getenv("Y_AGENT_HOME", "~/.y-agent")), "content")


def _fetch_detail(id_value):
    """Try activity_id first, then link_id. Returns dict or exits."""
    try:
        resp = api_request("GET", "/api/link/detail", params={"activity_id": id_value})
        return resp.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            pass
        else:
            raise
    try:
        resp = api_request("GET", "/api/link/detail", params={"link_id": id_value})
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
    """Get link details and content by activity_id or link_id."""
    link = _fetch_detail(id)

    click.echo(f"Link ID:   {link.get('link_id', '-')}")
    click.echo(f"URL:       {link.get('base_url') or link.get('url', '-')}")
    click.echo(f"Title:     {link.get('title') or '-'}")
    click.echo(f"Status:    {link.get('download_status') or '-'}")
    click.echo(f"Content:   {link.get('content_key') or '-'}")

    content_key = link.get('content_key')
    if not content_key:
        click.echo("\nNo content available")
        return

    # Try local cache first
    local_path = os.path.join(CONTENT_DIR, content_key)
    content = None
    if os.path.exists(local_path):
        with open(local_path, 'r') as f:
            content = f.read()
    else:
        # Download from S3 via API
        activity_id = link.get('activity_id')
        if not activity_id:
            click.echo("\nNo activity_id to fetch content", err=True)
            return
        try:
            resp = api_request("GET", "/api/link/content", params={"activity_id": activity_id})
            content = resp.json().get("content", "")
        except httpx.HTTPStatusError:
            click.echo("\nFailed to fetch content from server", err=True)
            return

        # Cache locally
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, 'w') as f:
            f.write(content)

    if output:
        with open(output, 'w') as f:
            f.write(content)
        click.echo(f"\nContent written to {output}")
    else:
        click.echo(f"\n--- Content ({len(content)} chars) ---")
        click.echo(content)
