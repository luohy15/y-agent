import os

import click

from yagent.api_client import api_request


@click.command('import-page')
@click.argument('paths', nargs=-1, required=True)
def link_import_page(paths):
    """Import markdown files as page:// links.

    Accepts one or more file paths. Use 'y link assoc' to associate with a todo.
    """
    for path in paths:
        if not os.path.isfile(path):
            click.echo(f"  ! File not found: {path}", err=True)
            continue

        title = os.path.basename(path).removesuffix('.md')
        try:
            resp = api_request("POST", "/api/link/from-page", json={"path": path, "title": title})
            data = resp.json()
            click.echo(f"  + {path} -> {data.get('link_id', '?')}")
        except Exception as e:
            click.echo(f"  ! {path}: {e}", err=True)
