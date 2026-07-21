import click

from yagent.api_client import api_request


@click.command("add")
@click.argument("entity_type")
@click.argument("entity_id")
@click.argument("tags", nargs=-1, required=True)
def tag_add(entity_type, entity_id, tags):
    """Add one or more TAGS to ENTITY_TYPE ENTITY_ID (writes into entity_tag)."""
    resp = api_request("POST", "/api/tag/add", json={
        "entity_type": entity_type, "entity_id": entity_id, "tags": list(tags),
    })
    added = resp.json()["added"]
    if added:
        click.echo(f"Added: {', '.join(added)}")
    else:
        click.echo("No new tags added (already present).")
