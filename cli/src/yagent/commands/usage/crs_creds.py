"""`y usage crs-creds`: bootstrap the stored CRS admin credentials."""

import click

from storage.service import model_usage_daily as usage_service
from storage.service import user_preference as user_pref_service
from storage.service.user import get_cli_user_id


@click.group("crs-creds")
def crs_creds():
    """Manage the Relay admin credentials used by direct run-rate reads."""


@crs_creds.command("set")
def set_creds():
    """Copy admin credentials from env or [crs] config into the database."""
    creds = usage_service._crs_admin_creds()
    user_pref_service.upsert_preference(get_cli_user_id(), "crs_admin", {
        "username": creds["username"],
        "password": creds["password"],
        "session_token": None,
        "token_expires_at": None,
    })
    click.echo("CRS admin credentials stored")


@crs_creds.command("show")
def show_creds():
    """Show stored credential state without printing its password or token."""
    pref = user_pref_service.get_preference(get_cli_user_id(), "crs_admin")
    value = pref.value if pref and isinstance(pref.value, dict) else None
    username = value.get("username") if isinstance(value, dict) else None
    password = value.get("password") if isinstance(value, dict) else None
    if not isinstance(username, str) or not username or not isinstance(password, str) or not password:
        click.echo("CRS admin credentials are not configured")
        return
    click.echo(f"username: {username}")
    click.echo("password: set")
