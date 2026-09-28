"""`y todo usage <todo_id>`: the chats on a trace and what they cost in tokens.

The numbers come from GET /api/trace/usage. Cost is shown as unavailable
because no per-request price is recorded, and historical completeness is
always unknown because a scan only covers the transcripts present when it ran.
"""

import json

import click
import httpx

from yagent.api_client import api_request


COUNTERS = (
    ("input_tokens", "in"),
    ("output_tokens", "out"),
    ("cache_creation_tokens", "cache_create"),
    ("cache_read_tokens", "cache_read"),
)


def _tokens(block: dict) -> str:
    """One counter line. A counter with missing rows says how many were missing."""
    parts = []
    missing = block.get("missing_requests") or {}
    for key, label in COUNTERS:
        text = f"{label}={block.get(key, 0)}"
        if missing.get(key):
            text += f" ({missing[key]} missing)"
        parts.append(text)
    return " ".join(parts)


def _age(seconds) -> str:
    if not isinstance(seconds, int):
        return "unknown age"
    if seconds < 90:
        return f"{seconds}s ago"
    if seconds < 90 * 60:
        return f"{seconds // 60}m ago"
    return f"{seconds // 3600}h ago"


def _scan_line(collection: dict) -> str:
    if collection.get("state") == "never_run":
        return "scan: never run"
    disclosures = collection.get("disclosures") or {}
    shown = []
    for key in (
        "files_unmatched", "files_in_progress", "files_failed", "malformed_lines",
        "rows_rejected", "unattributed_requests", "unsupported_subagent_requests",
    ):
        if disclosures.get(key):
            shown.append(f"{key}={disclosures[key]}")
    conflicts = disclosures.get("conflicts") or {}
    for field, count in conflicts.items():
        if count:
            shown.append(f"conflict_{field}={count}")
    detail = " ".join(shown) if shown else "none"
    return (
        f"scan: {_age(collection.get('scan_age_seconds'))} "
        f"outcome={collection.get('outcome')} disclosures: {detail}"
    )


def render(envelope: dict) -> str:
    """The text report. Tables are padded only as far as their own content."""
    lines = [
        _scan_line(envelope.get("collection") or {}),
        "historical completeness: unknown",
    ]
    tokens = envelope.get("tokens") or {}
    lines.append(
        f"totals: sessions={envelope.get('sessions', 0)} "
        f"transcripts={envelope.get('transcripts', 0)} "
        f"turns={envelope.get('turns', 0)} "
        f"inbound={envelope.get('inbound', 0)} "
        f"requests={envelope.get('requests', 0)} "
        f"{_tokens(tokens)}"
    )
    lines.append("cost: unavailable (no recorded per-request cost)")

    lines.append("")
    lines.append("per model")
    models = envelope.get("models") or []
    if not models:
        lines.append("  (none)")
    for model in models:
        lines.append(f"  {model['model']}  requests={model['requests_observed']} {_tokens(model)}")

    lines.append("")
    lines.append("per chat (oldest first)")
    chats = sorted(envelope.get("chats") or [], key=lambda chat: chat.get("created_at_unix") or 0)
    if not chats:
        lines.append("  (none)")
    for chat in chats:
        who = " ".join(
            part for part in (chat.get("skill"), chat.get("bot_name"), chat.get("tier")) if part
        ) or "-"
        if chat.get("collected") is False:
            # Turns and inbound come from the chat itself, so they still apply.
            lines.append(
                f"  {chat['chat_id']}  {who}  turns={chat.get('turns', 0)} "
                f"inbound={chat.get('inbound', 0)} "
                f"requests not collected ({chat.get('reason', 'unknown')})"
            )
            continue
        lines.append(
            f"  {chat['chat_id']}  {who}  turns={chat.get('turns', 0)} "
            f"inbound={chat.get('inbound', 0)} requests={chat.get('requests_observed', 0)} "
            f"{_tokens(chat)}"
        )
    return "\n".join(lines)


def fetch_usage(todo_id: str) -> dict:
    try:
        resp = api_request("GET", "/api/trace/usage", params={"trace_id": todo_id})
    except httpx.HTTPStatusError as exc:
        raise click.ClickException(str(exc)) from exc
    return resp.json()


@click.command("usage")
@click.argument("todo_id")
@click.option("--json", "as_json", is_flag=True, help="Print the raw response instead of the report")
def todo_usage(todo_id, as_json):
    """Show bot usage for every chat on a todo's trace."""
    envelope = fetch_usage(todo_id)
    if as_json:
        click.echo(json.dumps(envelope, default=str))
        return
    click.echo(render(envelope))
