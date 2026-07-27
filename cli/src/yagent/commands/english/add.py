import click

from yagent.api_client import api_request


@click.command("add")
@click.option("--chat-id", required=True, help="Public chat id of the source message")
@click.option("--message-id", required=True, help="Source message id")
@click.option("--message-at", required=True, help="Source message UTC ISO 8601 timestamp")
@click.option("--message-at-unix", required=True, type=int, help="Source message unix ms")
@click.option("--original", "original_text", required=True, help="Full original message text")
@click.option("--corrected", "corrected_text", required=True, help="Minimally corrected text")
@click.option(
    "--categories",
    default="",
    help="Comma-separated free-form error categories (e.g. tense,article)",
)
@click.option("--explanation", required=True, help="Short grammar explanation")
def english_add(
    chat_id,
    message_id,
    message_at,
    message_at_unix,
    original_text,
    corrected_text,
    categories,
    explanation,
):
    """Add a correction (idempotent on chat_id + message_id)."""
    cats = [c.strip() for c in categories.split(",") if c.strip()] if categories else []
    body = {
        "chat_id": chat_id,
        "message_id": message_id,
        "message_at": message_at,
        "message_at_unix": message_at_unix,
        "original_text": original_text,
        "corrected_text": corrected_text,
        "error_categories": cats,
        "explanation": explanation,
    }
    resp = api_request("POST", "/api/english", json=body)
    row = resp.json()
    click.echo(
        f"Correction {row['correction_id']} chat={row['chat_id']} msg={row['message_id']} "
        f"cats={','.join(row.get('error_categories') or []) or '-'}"
    )
