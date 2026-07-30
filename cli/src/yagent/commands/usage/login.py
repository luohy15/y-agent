"""`y usage login <openai|xai>` and `y usage credentials` -- provider grant
bootstrap and status for the provider-usage credential store (sub-task 1).

Both providers are import-only today: each forks a grant out of the vendor
CLI's own credential file into y-agent's own record (never writes back to
the vendor file). `--path` exists purely so this is testable against a fixed
fixture file instead of ever touching `~/.codex/auth.json` /
`~/.grok/auth.json` directly.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import click

from . import _credentials as store
from ._oauth import _decode_jwt_payload


def _import_openai_from_codex(path: str | None) -> dict:
    """Parse the Codex CLI's own credential file into a provider-usage
    record. `chatgpt_account_id` is needed later for the `codex_usage_api`
    reader's `chatgpt-account-id` header."""
    codex_path = Path(path) if path else Path(os.path.expanduser("~/.codex/auth.json"))
    if not codex_path.is_file():
        raise click.ClickException(f"{codex_path} not found -- run `codex login` first")
    try:
        data = json.loads(codex_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise click.ClickException(f"{codex_path} is not valid JSON: {exc}") from exc

    tokens = data.get("tokens") or {}
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise click.ClickException(
            f"{codex_path} has no tokens.refresh_token -- run a real `codex login` "
            "(ChatGPT sign-in, not an API key) first"
        )

    extra: dict = {}
    id_token = tokens.get("id_token")
    if id_token:
        claims = _decode_jwt_payload(id_token) or {}
        auth_claim = claims.get("https://api.openai.com/auth") or {}
        if auth_claim.get("chatgpt_account_id"):
            extra["chatgpt_account_id"] = auth_claim["chatgpt_account_id"]
    if tokens.get("account_id") and "chatgpt_account_id" not in extra:
        extra["chatgpt_account_id"] = tokens["account_id"]

    return {
        "refresh_token": refresh_token,
        "access_token": tokens.get("access_token"),
        "expires_at": None,
        "scopes": None,
        "extra": extra or None,
        "status": "active",
        "last_refresh_at": None,
        "last_error": None,
    }


def _find_grok_credential_record(data) -> dict | None:
    """The real `~/.grok/auth.json` nests the credential record under a
    dynamic `"{oidc_issuer}::{oidc_client_id}"` key (live discovery, todo
    2872) rather than at the top level -- the plan's flat-shape assumption
    came from decompiled binary strings, never a live file. Support both:
    a flat top-level record (defensive / for fixtures) and the real nested
    shape (first value that looks like a credential record)."""
    if not isinstance(data, dict):
        return None
    if data.get("refresh_token"):
        return data
    for value in data.values():
        if isinstance(value, dict) and value.get("refresh_token"):
            return value
    return None


def _import_xai_from_grok(path: str | None) -> dict:
    """Parse the Grok CLI's own credential file into a provider-usage
    record. `key` is the access token, `refresh_token` / `expires_at` are as
    named (see `_find_grok_credential_record` for the real nesting)."""
    grok_path = Path(path) if path else Path(os.path.expanduser("~/.grok/auth.json"))
    if not grok_path.is_file():
        raise click.ClickException(f"{grok_path} not found -- run `grok login` first")
    try:
        data = json.loads(grok_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise click.ClickException(f"{grok_path} is not valid JSON: {exc}") from exc

    record_data = _find_grok_credential_record(data)
    if record_data is None:
        raise click.ClickException(f"{grok_path} has no refresh_token -- run `grok login` first")

    return {
        "refresh_token": record_data["refresh_token"],
        "access_token": record_data.get("key"),
        "expires_at": record_data.get("expires_at"),
        "scopes": None,
        "extra": None,
        "status": "active",
        "last_refresh_at": None,
        "last_error": None,
    }


@click.command("login")
@click.argument("provider", type=click.Choice(store.PROVIDERS))
@click.option("--from-codex", is_flag=True, help="Import the grant from ~/.codex/auth.json (openai only)")
@click.option(
    "--from-grok",
    is_flag=True,
    help="Import the grant from ~/.grok/auth.json (xai only) -- forks the grant, re-run `grok login` afterwards",
)
@click.option("--path", default=None, help="Override the source file path for --from-codex/--from-grok (testing)")
def login(provider: str, from_codex: bool, from_grok: bool, path: str | None):
    """Register a provider grant in the provider-usage credential store."""
    if provider == "openai":
        if not from_codex:
            raise click.ClickException("openai login currently requires --from-codex (run `codex login` first)")
        record = _import_openai_from_codex(path)
    else:  # xai
        if not from_grok:
            raise click.ClickException("xai login currently requires --from-grok (run `grok login` first)")
        record = _import_xai_from_grok(path)

    store.set_record(provider, record)
    suffix = f" {record['expires_at']}" if record.get("expires_at") else ""
    click.echo(f"{provider} active{suffix}")
    if provider == "xai" and from_grok:
        click.echo(
            "Importing forks the grant the `grok` CLI still uses -- run `grok login` again "
            "afterwards so it keeps a working grant of its own.",
            err=True,
        )


@click.command("credentials")
def credentials():
    """Print each provider's stored grant status (never token material)."""
    data = store.load_store()
    for provider in store.PROVIDERS:
        record = data.get(provider)
        if not record:
            click.echo(f"{provider} not_configured")
            continue
        status = record.get("status") or "unknown"
        expires_at = record.get("expires_at") or "-"
        click.echo(f"{provider} {status} {expires_at}")
