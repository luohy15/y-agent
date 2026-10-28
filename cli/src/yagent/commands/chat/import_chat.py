import os
import json
from datetime import datetime
from typing import Dict
import click

from storage.entity.dto import Chat
from storage.repository import chat as chat_repo
from yagent.config import config

@click.command('import')
@click.argument('file_path', type=click.Path(exists=True, readable=True))
@click.option('--verbose', '-v', is_flag=True, help='Show detailed information')
def import_chats(file_path: str, verbose: bool = False):
    """Import chats from an external JSONL file.

    The import follows these rules:
    1. If chat ID doesn't exist, import it
    2. If chat ID exists, compare update times and use the more recent one
    3. Prints summary of new, existing, and replaced chats
    """
    if verbose:
        click.echo(f"Importing chats from: {file_path}")
        click.echo(f"Current database: {config['database_url']}")

    # Read source chats from JSONL file
    source_chats = []
    with open(os.path.expanduser(file_path), 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                source_chats.append(Chat.from_dict(json.loads(line)))

    # Read current chats
    current_chats = chat_repo._read_chats()

    if verbose:
        click.echo(f"Found {len(source_chats)} chats in source file")
        click.echo(f"Found {len(current_chats)} chats in current database")

    # Track statistics
    new_count = 0
    existing_count = 0
    replaced_count = 0

    # Create a map of current chats by ID for efficient lookup
    current_chats_map: Dict[str, Chat] = {chat.id: chat for chat in current_chats}

    # Process each source chat
    for source_chat in source_chats:
        if source_chat.id not in current_chats_map:
            current_chats_map[source_chat.id] = source_chat
            new_count += 1
            if verbose:
                click.echo(f"Importing new chat: {source_chat.id}")
        else:
            existing_count += 1
            current_chat = current_chats_map[source_chat.id]

            source_time = datetime.fromisoformat(source_chat.update_time.replace('Z', '+00:00'))
            current_time = datetime.fromisoformat(current_chat.update_time.replace('Z', '+00:00'))

            if source_time > current_time:
                current_chats_map[source_chat.id] = source_chat
                replaced_count += 1
                if verbose:
                    click.echo(f"Replacing chat with newer version: {source_chat.id}")
            else:
                if verbose:
                    click.echo(f"Keeping existing chat (newer): {current_chat.id}")

    # Write updated chats back
    updated_chats = list(current_chats_map.values())
    chat_repo._write_chats(updated_chats)

    # Print statistics
    click.echo("Import completed:")
    click.echo(f"  New chats: {new_count}")
    click.echo(f"  Existing chats: {existing_count}")
    click.echo(f"  Replaced chats: {replaced_count}")
