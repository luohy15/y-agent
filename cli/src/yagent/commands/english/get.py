import click

from yagent.api_client import api_request
from yagent.time_util import utc_to_local


@click.command("get")
@click.argument("correction_id")
def english_get(correction_id):
    """Get one correction by public id."""
    resp = api_request("GET", "/api/english/detail", params={"correction_id": correction_id})
    r = resp.json()
    cats = ", ".join(r.get("error_categories") or []) or "-"
    click.echo(f"ID:           {r['correction_id']}")
    click.echo(f"Dismissed:    {'yes' if r.get('dismissed') else 'no'}")
    click.echo(f"Chat:         {r.get('chat_id')}")
    click.echo(f"Message:      {r.get('message_id')}")
    click.echo(f"Message at:   {utc_to_local(r['message_at']) if r.get('message_at') else '-'}")
    click.echo(f"Categories:   {cats}")
    click.echo(f"Original:     {r.get('original_text')}")
    click.echo(f"Corrected:    {r.get('corrected_text')}")
    click.echo(f"Explanation:  {r.get('explanation')}")
    if r.get("created_at"):
        click.echo(f"Created:      {utc_to_local(r['created_at'])}")
