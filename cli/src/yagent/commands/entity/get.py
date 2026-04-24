import json

import click

from yagent.api_client import api_request


@click.command("get")
@click.argument("entity_id")
def entity_get(entity_id):
    """Get entity details (with associated notes and rss feeds)."""
    resp = api_request("GET", "/api/entity/detail", params={"entity_id": entity_id})
    entity = resp.json()
    click.echo(f"ID:          {entity['entity_id']}")
    click.echo(f"Name:        {entity['name']}")
    click.echo(f"Type:        {entity['type']}")
    if entity.get("front_matter"):
        click.echo(f"Front Matter: {json.dumps(entity['front_matter'], ensure_ascii=False)}")
    if entity.get("created_at"):
        click.echo(f"Created:     {entity['created_at']}")
    if entity.get("updated_at"):
        click.echo(f"Updated:     {entity['updated_at']}")

    notes_resp = api_request("GET", "/api/entity-note/by-entity", params={"entity_id": entity_id})
    note_ids = notes_resp.json()
    if note_ids:
        click.echo("Notes:")
        for nid in note_ids:
            click.echo(f"  - {nid}")

    rss_resp = api_request("GET", "/api/entity-rss/by-entity", params={"entity_id": entity_id})
    rss_ids = rss_resp.json()
    if rss_ids:
        click.echo("RSS feeds:")
        for rid in rss_ids:
            click.echo(f"  - {rid}")

    links_resp = api_request("GET", "/api/entity-link/by-entity", params={"entity_id": entity_id})
    activity_ids = links_resp.json()
    if activity_ids:
        click.echo("Links:")
        for aid in activity_ids:
            click.echo(f"  - {aid}")
