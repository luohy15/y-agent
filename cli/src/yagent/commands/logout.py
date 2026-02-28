"""Logout command — remove stored credentials."""

import click

from yagent.api_client import remove_auth


@click.command("logout")
def logout():
    """Remove stored authentication credentials."""
    remove_auth()
    click.echo("Logged out.")
