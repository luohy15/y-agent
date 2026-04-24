import click

from yagent.api_client import api_request


@click.command("import-link")
@click.argument("activity_id")
@click.option("--name", required=True, help="Entity name")
@click.option("--type", "type_", required=True, help="Entity type (e.g. person, product)")
@click.option("-f", "fields", multiple=True, help="Extra front_matter key=val entries (repeatable)")
def entity_import_link(activity_id, name, type_, fields):
    """Import a link (by activity_id) as an entity — upsert entity + create entity-link relation."""
    front_matter = {}
    for kv in fields:
        if "=" not in kv:
            click.echo(f"Invalid -f value (expected key=val): {kv}", err=True)
            raise SystemExit(1)
        k, v = kv.split("=", 1)
        front_matter[k.strip()] = v.strip()

    payload = {"name": name, "type": type_}
    if front_matter:
        payload["front_matter"] = front_matter
    resp = api_request("POST", "/api/entity/import", json=payload)
    entity = resp.json()
    entity_id = entity["entity_id"]
    click.echo(f"Entity: {entity_id} ({name} [{type_}])")

    link_resp = api_request("POST", "/api/entity-link", json={"entity_id": entity_id, "activity_id": activity_id})
    data = link_resp.json()
    if data.get("created"):
        click.echo(f"Linked entity {entity_id} to activity {activity_id}")
    else:
        click.echo(f"Association already exists: entity {entity_id} <-> activity {activity_id}")
