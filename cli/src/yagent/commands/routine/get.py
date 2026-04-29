import click

from yagent.api_client import api_request
from yagent.time_util import utc_to_local


@click.command('get')
@click.argument('routine_id')
def routine_get(routine_id):
    """Show routine details."""
    resp = api_request("GET", "/api/routine/detail", params={"routine_id": routine_id})
    r = resp.json()

    click.echo(f"ID:        {r['routine_id']}")
    click.echo(f"Name:      {r['name']}")
    click.echo(f"Schedule:  {r['schedule']}")
    click.echo(f"Enabled:   {'yes' if r.get('enabled') else 'no'}")
    if r.get('target_topic'):
        click.echo(f"Topic:     {r['target_topic']}")
    if r.get('target_skill'):
        click.echo(f"Skill:     {r['target_skill']}")
    if r.get('work_dir'):
        click.echo(f"Work Dir:  {r['work_dir']}")
    if r.get('backend'):
        click.echo(f"Backend:   {r['backend']}")
    click.echo(f"Message:   {r['message']}")
    if r.get('description'):
        click.echo(f"Desc:      {r['description']}")
    if r.get('last_run_at'):
        click.echo(f"Last Run:  {utc_to_local(r['last_run_at'])}")
    if r.get('last_run_status'):
        click.echo(f"Status:    {r['last_run_status']}")
    if r.get('last_chat_id'):
        click.echo(f"Last Chat: {r['last_chat_id']}")
    if r.get('created_at'):
        click.echo(f"Created:   {r['created_at']}")
    if r.get('updated_at'):
        click.echo(f"Updated:   {r['updated_at']}")
