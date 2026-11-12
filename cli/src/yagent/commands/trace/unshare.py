from typing import Optional
import click
import httpx

from yagent.api_client import api_request


@click.command('unshare')
@click.argument('share_id', required=False)
@click.option('--trace-id', '-t', help='Unshare by todo ID (looks up current share first)')
def trace_unshare(share_id: Optional[str], trace_id: Optional[str]):
    """Delete a todo chat share link.

    Pass SHARE_ID directly, or use --trace-id to look up and delete the current share for a todo.
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
            body = resp.json()
            # Current servers return JSON null when the trace has no share.
            # A 404 below is the same answer from an older server.
            if body is None:
                click.echo(f"No share found for todo {trace_id}")
                raise click.Abort()
            share_id = body["share_id"]
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                click.echo(f"No share found for todo {trace_id}")
                raise click.Abort() from e
            raise

    try:
        api_request("DELETE", "/api/trace/share", params={"share_id": share_id})
        click.echo(f"Deleted share {share_id}")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            click.echo(f"Share {share_id} not found")
            raise click.Abort() from e
        raise
