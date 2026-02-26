"""Import Claude Code conversation history from ~/.claude/projects/ into y-agent."""

import os
import click

from sqlalchemy import inspect as sa_inspect, text

import json

from storage.util import generate_id
from storage.entity.dto import Chat
from storage.repository.chat import find_external_id_map, _extract_title
from storage.database.base import get_db
from storage.service.user import get_cli_user_id
from agent.claude_code import convert_history_session, _iso_to_unix_ms
from yagent.config import config  # noqa: F401 - triggers DB init


def _upsert_import_chat(user_id: int, chat: Chat, existing_chat_id: str | None = None):
    """Insert or update an imported chat, preserving session timestamps.

    Uses raw SQL to bypass SQLAlchemy's default/onupdate hooks.
    """
    params = {
        "title": _extract_title(chat),
        "eid": chat.external_id,
        "backend": chat.backend,
        "ocid": chat.origin_chat_id,
        "jc": json.dumps(chat.to_dict()),
        "ca": chat.create_time,
        "ua": chat.update_time,
        "cau": _iso_to_unix_ms(chat.create_time),
        "uau": _iso_to_unix_ms(chat.update_time),
    }
    with get_db() as session:
        if existing_chat_id:
            params["cid"] = existing_chat_id
            session.execute(
                text(
                    "UPDATE chat SET title = :title, json_content = :jc,"
                    " updated_at = :ua, updated_at_unix = :uau"
                    " WHERE chat_id = :cid"
                ),
                params,
            )
        else:
            params["uid"] = user_id
            params["cid"] = chat.id
            session.execute(
                text(
                    "INSERT INTO chat (user_id, chat_id, title, external_id, backend, origin_chat_id, json_content,"
                    " created_at, updated_at, created_at_unix, updated_at_unix)"
                    " VALUES (:uid, :cid, :title, :eid, :backend, :ocid, :jc, :ca, :ua, :cau, :uau)"
                ),
                params,
            )


def _ensure_columns():
    """Add external_id/backend columns and backfill from json_content."""
    with get_db() as session:
        inspector = sa_inspect(session.bind)
        columns = [c["name"] for c in inspector.get_columns("chat")]
        if "external_id" not in columns:
            session.execute(text("ALTER TABLE chat ADD COLUMN external_id VARCHAR"))
            session.execute(text("CREATE INDEX IF NOT EXISTS ix_chat_external_id ON chat (external_id)"))
            click.echo("Added external_id column to chat table")
        if "backend" not in columns:
            session.execute(text("ALTER TABLE chat ADD COLUMN backend VARCHAR"))
            click.echo("Added backend column to chat table")
        # Backfill external_id/backend from json_content for existing worker chats
        count = session.execute(text(
            "UPDATE chat SET"
            " external_id = json_content::json->>'external_id',"
            " backend = 'claude_code'"
            " WHERE json_content::json->>'external_id' IS NOT NULL"
            " AND (external_id IS NULL OR backend IS NULL)"
        )).rowcount
        if count:
            click.echo(f"Backfilled {count} existing chats with external_id/backend")


@click.command("import-claude")
@click.option("--source", default="~/.claude/projects", help="Path to Claude projects dir")
@click.option("--project", "-p", default=None, help="Only import a specific project subfolder")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed information")
def import_claude(source: str, project: str | None, verbose: bool):
    """Import Claude Code history into y-agent (re-runnable / incremental)."""
    _ensure_columns()

    source = os.path.expanduser(source)
    if not os.path.isdir(source):
        click.echo(f"Source directory not found: {source}")
        raise click.Abort()

    user_id = get_cli_user_id()

    # Collect JSONL files to process
    jsonl_files: list[tuple[str, str]] = []  # (project_name, filepath)
    if project:
        proj_dir = os.path.join(source, project)
        if not os.path.isdir(proj_dir):
            click.echo(f"Project directory not found: {proj_dir}")
            raise click.Abort()
        projects = [(project, proj_dir)]
    else:
        projects = []
        for name in sorted(os.listdir(source)):
            d = os.path.join(source, name)
            if os.path.isdir(d):
                projects.append((name, d))

    for proj_name, proj_dir in projects:
        for fname in sorted(os.listdir(proj_dir)):
            if fname.endswith(".jsonl"):
                jsonl_files.append((proj_name, os.path.join(proj_dir, fname)))

    if verbose:
        click.echo(f"Found {len(jsonl_files)} JSONL files across {len(projects)} project(s)")

    # Build dedup map: external_id -> chat_id
    existing_map = find_external_id_map(user_id, "claude_code")
    if verbose:
        click.echo(f"Existing imported sessions: {len(existing_map)}")

    new_count = 0
    updated_count = 0
    skip_count = 0
    error_count = 0

    for proj_name, filepath in jsonl_files:
        fname = os.path.basename(filepath)
        session_uuid = fname.removesuffix(".jsonl")
        external_id = session_uuid

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                lines = f.readlines()

            messages, session_id, work_dir = convert_history_session(lines)

            if not messages:
                skip_count += 1
                if verbose:
                    click.echo(f"  skip (empty): {proj_name}/{fname}")
                continue

            first_ts = messages[0].timestamp
            last_ts = messages[-1].timestamp
            existing_chat_id = existing_map.get(external_id)

            chat = Chat(
                id=existing_chat_id or generate_id(),
                create_time=first_ts,
                update_time=last_ts,
                messages=messages,
                external_id=external_id,
                backend="claude_code",
                work_dir=work_dir,
            )

            _upsert_import_chat(user_id, chat, existing_chat_id)

            if existing_chat_id:
                updated_count += 1
                if verbose:
                    click.echo(f"  updated: {proj_name}/{fname} -> {existing_chat_id} ({len(messages)} msgs)")
            else:
                existing_map[external_id] = chat.id
                new_count += 1
                if verbose:
                    title = ""
                    for m in messages:
                        if m.role == "user":
                            title = (m.content[:80] if isinstance(m.content, str) else "")
                            break
                    click.echo(f"  imported: {proj_name}/{fname} -> {chat.id} ({len(messages)} msgs) {title}")

        except Exception as e:
            error_count += 1
            click.echo(f"  ERROR: {proj_name}/{fname}: {e}")

    click.echo(f"Import completed: {new_count} new, {updated_count} updated, {skip_count} skipped, {error_count} errors")
