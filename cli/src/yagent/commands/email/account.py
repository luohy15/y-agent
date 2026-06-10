import click
from yagent.api_client import api_request


@click.group('account')
def email_account_group():
    """Manage connected Gmail accounts."""
    pass


@email_account_group.command('list')
def email_account_list():
    """List connected Gmail accounts."""
    resp = api_request("GET", "/api/email/account/list")
    accounts = resp.json()
    if not accounts:
        click.echo("No accounts registered. Add one with: y email account add <address> <app_password>")
        return
    for a in accounts:
        click.echo(a["address"])


@email_account_group.command('add')
@click.argument('address')
@click.argument('app_password')
def email_account_add(address, app_password):
    """Register a Gmail account with its IMAP app password.

    Generate an app password at https://myaccount.google.com/apppasswords
    (requires 2FA). Re-adding an existing address updates its password.
    """
    resp = api_request("POST", "/api/email/account", json={
        "address": address,
        "app_password": app_password,
    })
    click.echo(f"Registered account {resp.json()['address']}")


@email_account_group.command('rm')
@click.argument('address')
def email_account_rm(address):
    """Remove a connected Gmail account. Synced emails are kept."""
    api_request("DELETE", f"/api/email/account/{address}")
    click.echo(f"Removed account {address}")
