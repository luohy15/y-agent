import click

from yagent.api_client import api_request


@click.command("rm")
@click.argument("entity_type")
@click.argument("entity_id")
@click.argument("tags", nargs=-1, required=True)
def tag_rm(entity_type, entity_id, tags):
    """Remove one or more TAGS from ENTITY_TYPE ENTITY_ID (deletes from entity_tag)."""
    resp = api_request("POST", "/api/tag/remove", json={
        "entity_type": entity_type, "entity_id": entity_id, "tags": list(tags),
    })
    removed = resp.json()["removed"]
    if removed:
        click.echo(f"Removed: {', '.join(removed)}")
    else:
        click.echo("No tags removed (not present).")
