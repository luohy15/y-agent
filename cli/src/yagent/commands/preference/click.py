import click

from storage.service.user_preference import DEFAULT_LANGUAGE, LANGUAGE_KEY, LANGUAGES

from yagent.api_client import api_request

_VALUE_CHOICES = click.Choice([*LANGUAGES, "default"])


@click.group("preference")
def preference_group():
    """Read or set your personal preferences."""


@preference_group.command("get")
@click.argument("key", type=click.Choice([LANGUAGE_KEY]), metavar="language")
def preference_get(key):
    """Print the effective value of a preference."""
    payload = api_request("GET", "/api/user-preference", params={"key": key}).json()
    stored = payload.get("value")
    click.echo(stored if stored in LANGUAGES else DEFAULT_LANGUAGE)


@preference_group.command("set")
@click.argument("key", type=click.Choice([LANGUAGE_KEY]), metavar="language")
@click.argument("value", type=_VALUE_CHOICES, metavar="{en|zh|default}")
def preference_set(key, value):
    """Set a preference; `default` clears it.

    The language drives stored todo fields and agent notices: `en` (default)
    or `zh`.
    """
    if value == "default":
        api_request("DELETE", "/api/user-preference", params={"key": key})
        click.echo(DEFAULT_LANGUAGE)
        return
    api_request("PUT", "/api/user-preference", json={"key": key, "value": value})
    click.echo(value)
