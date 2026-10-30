"""`y usage limits [--json] [--refresh]` (todo 2872 sub-task 3, Claude reader
removed in todo 4138): the two readers -- `codex_usage_api` and
`xai_billing_credits` (direct HTTP, `_http_readers.py`) -- behind one
envelope. Emits exactly the `{"providers": [...], "errors": [...]}` shape
`storage.service.model_usage_limits.normalize_envelope` expects; this is the
contract `agent.usage_limits`'s SSH wrapper and `GET /api/usage/limits` are
built against. No provider-selector flag: callers take the whole envelope.

Readers never raise for an ordinary provider-level failure (not_logged_in /
reauth_required / parse_failed / transport_error all come back as a row);
`asyncio.gather(..., return_exceptions=True)` is only the backstop for a
genuine bug in one reader, so it can't take the other down with it --
that failure is isolated into the envelope's `errors`, not a crashed
command.
"""

from __future__ import annotations

import asyncio
import json

import click
from loguru import logger

from . import _http_readers

_WINDOW_LABELS = (
    ("five_hour", "5 hours"),
    ("one_week", "1 week"),
    ("billing_period", "Billing period"),
)


async def _collect(refresh: bool) -> dict:
    # `--refresh` stays accepted. The agent retry still passes it, and both
    # remaining readers always run fresh, so the flag does not change the read.
    del refresh
    sources = ("codex_usage_api", "xai_billing_credits")
    tasks = (
        asyncio.to_thread(_http_readers.read_codex_provider),
        asyncio.to_thread(_http_readers.read_xai_provider),
    )
    results = await asyncio.gather(*tasks, return_exceptions=True)

    providers = []
    errors = []
    for source, result in zip(sources, results, strict=True):
        if isinstance(result, Exception):
            logger.warning("y usage limits: reader {} raised: {}", source, result)
            errors.append({"origin": source, "error": "transport_error"})
            continue
        providers.append(result)

    return {"providers": providers, "errors": errors}


@click.command("limits")
@click.option("--json", "as_json", is_flag=True, help="Output the raw JSON envelope instead of a table")
@click.option("--refresh", is_flag=True, help="Accepted for callers; Codex and Grok always run fresh")
def limits(as_json: bool, refresh: bool):
    """Read live subscription limit-window usage for Codex and Grok."""
    envelope = asyncio.run(_collect(refresh))

    if as_json:
        click.echo(json.dumps(envelope))
        return

    _print_table(envelope)


def _print_table(envelope: dict) -> None:
    click.echo(f"{'Provider':<10} {'Window':<16} {'Used':>6}  {'Status':<16} Reset")
    click.echo("-" * 72)
    for item in envelope["providers"]:
        provider = item.get("provider") or "?"
        windows = item.get("windows") or {}
        printed = False
        for kind, label in _WINDOW_LABELS:
            window = windows.get(kind)
            if not window:
                continue
            printed = True
            pct = window.get("used_percent")
            pct_str = f"{pct:.0f}%" if pct is not None else "-"
            click.echo(
                f"{provider:<10} {label:<16} {pct_str:>6}  {item.get('availability', '-'):<16} "
                f"{window.get('reset_at') or '-'}"
            )
        if not printed:
            click.echo(
                f"{provider:<10} {'-':<16} {'-':>6}  {item.get('availability', '-'):<16} "
                f"{item.get('error') or '-'}"
            )
    for err in envelope.get("errors") or []:
        click.echo(f"error: {err.get('origin')} -> {err.get('error')}", err=True)
