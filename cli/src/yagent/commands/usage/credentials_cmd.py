"""`y usage credentials` -- read-through status for the provider-usage
credential layer (todo 2872 read-through redesign).

There is no more `y usage login`: read-through means there is nothing to
import. This command reports, per provider, whether the vendor CLI's own
credential file holds a usable grant -- it never prints token material.
Since there is no persisted y-agent-side status to read back, a stale
access token is exercised through the real `ensure_access_token` refresh
path (writing the rotated grant back into the vendor file on success, same
as any other read) rather than guessed at.
"""

from __future__ import annotations

import click

from . import _credentials as vendor
from . import _refresh
from ._errors import CredentialsMissingError, ReauthRequiredError


@click.command("credentials")
def credentials():
    """Print each provider's vendor-file credential status (never token material)."""
    for provider in vendor.PROVIDERS:
        try:
            _refresh.ensure_access_token(provider)
        except CredentialsMissingError:
            click.echo(f"{provider} not_logged_in")
            continue
        except ReauthRequiredError:
            click.echo(f"{provider} reauth_required")
            continue
        click.echo(f"{provider} active")
