"""Admin surface for dormant tenant encryption. Enable does not turn a tenant on."""

import click

from yagent.api_client import api_request


@click.group(name="tenant-encryption")
def tenant_encryption_group():
    """Inspect or crypto-shred tenant keys. Enabling a tenant is refused."""


@tenant_encryption_group.command(name="status")
@click.option("--user-id", required=True, type=int)
def status(user_id: int):
    response = api_request("GET", "/api/tenant-encryption/status", params={"user_id": user_id})
    click.echo(response.text)


@tenant_encryption_group.command(name="enable")
@click.option("--user-id", required=True, type=int)
def enable(user_id: int):
    """Always refused: existing accounts stay plaintext, and todo 4371 is still open."""
    response = api_request("POST", "/api/tenant-encryption/enable", json={"user_id": user_id})
    click.echo(response.text)


@tenant_encryption_group.command(name="rotate-dek")
@click.option("--user-id", required=True, type=int)
def rotate_dek(user_id: int):
    response = api_request("POST", "/api/tenant-encryption/rotate-dek", json={"user_id": user_id})
    click.echo(response.text)


@tenant_encryption_group.command(name="shred")
@click.option("--user-id", required=True, type=int)
def shred(user_id: int):
    """Delete wrapped DEKs. Live ciphertext becomes unreadable after the backup window."""
    response = api_request("POST", "/api/tenant-encryption/shred", json={"user_id": user_id})
    click.echo(response.text)
