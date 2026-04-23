from typing import Optional
import click
import httpx

from yagent.api_client import api_request


@click.command('unshare')
@click.argument('share_id', required=False)
@click.option('--trace-id', '-t', help='Unshare by trace ID (looks up current share first)')
def trace_unshare(share_id: Optional[str], trace_id: Optional[str]):
    """Delete a trace share link.

    Pass SHARE_ID directly, or use --trace-id to look up and delete the current share for a trace.
    """
    if not share_id and not trace_id:
        click.echo("Error: provide SHARE_ID or --trace-id")
        raise click.Abort()
    if share_id and trace_id:
        click.echo("Error: pass either SHARE_ID or --trace-id, not both")
        raise click.Abort()

    if trace_id:
        try:
            resp = api_request("GET", "/api/trace/share/mine", params={"trace_id": trace_id})
            share_id = resp.json()["share_id"]
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                click.echo(f"No share found for trace {trace_id}")
                raise click.Abort()
            raise

    try:
        api_request("DELETE", "/api/trace/share", params={"share_id": share_id})
        click.echo(f"Deleted share {share_id}")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            click.echo(f"Share {share_id} not found")
            raise click.Abort()
        raise
