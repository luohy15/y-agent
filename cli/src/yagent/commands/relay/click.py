"""`y relay credential`: status and maintainer provisioning of a per-user relay key."""

import json

import click
import httpx

from yagent.api_client import api_request


@click.group("relay")
def relay_group():
    """Per-user relay credentials."""


@click.group("credential")
def credential_group():
    """Read or provision the sealed relay key for a y-agent user."""


def _call(method: str, path: str, body: dict | None = None):
    try:
        response = api_request(method, path, timeout=60, json=body)
    except httpx.HTTPStatusError as exc:
        raise click.ClickException(str(exc)) from exc
    payload = response.json()
    if isinstance(payload, dict) and "api_key" in payload:
        raise click.ClickException("refusing to print a relay secret")
    click.echo(json.dumps(payload))


@credential_group.command("status")
def status():
    """Show the signed-in user's relay credential without its secret."""
    _call("GET", "/api/relay-credential")


@credential_group.command("provision")
@click.option("--user", "public_user_id", default=None, help="Public user id. Defaults to the signed-in user.")
@click.option("--rotate", is_flag=True, help="Replace an existing yagent-user key.")
def provision(public_user_id: str | None, rotate: bool):
    """Create a relay key from the subscription template and seal it."""
    body = {"action": "rotate" if rotate else "provision"}
    if public_user_id:
        body["user_id"] = public_user_id
    _call("POST", "/api/relay-credential", body)


@credential_group.command("set")
@click.option("--api-key", required=True, help="Relay key to seal. It is not printed back.")
@click.option("--user", "public_user_id", default=None, help="Public user id. Defaults to the signed-in user.")
@click.option("--billing-mode", type=click.Choice(["real", "notional"]), default=None)
@click.option("--relay-key-id", default=None)
@click.option("--origin", "relay_origin", default=None)
def set_key(api_key: str, public_user_id: str | None, billing_mode: str | None, relay_key_id: str | None, relay_origin: str | None):
    """Seal an existing relay key. The response never includes the secret."""
    body = {"action": "set", "api_key": api_key}
    if public_user_id:
        body["user_id"] = public_user_id
    if billing_mode:
        body["billing_mode"] = billing_mode
    if relay_key_id:
        body["relay_key_id"] = relay_key_id
    if relay_origin:
        body["relay_origin"] = relay_origin
    _call("POST", "/api/relay-credential", body)


@credential_group.command("rotate")
@click.option("--user", "public_user_id", default=None, help="Public user id. Defaults to the signed-in user.")
def rotate(public_user_id: str | None):
    """Create a replacement key and retire the previously stored relay key id."""
    body = {"action": "rotate"}
    if public_user_id:
        body["user_id"] = public_user_id
    _call("POST", "/api/relay-credential", body)


relay_group.add_command(credential_group)
