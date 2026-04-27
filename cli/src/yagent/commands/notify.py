import click
import httpx

from yagent.api_client import api_request


@click.command('notify')
@click.option('--message', '-m', required=True, help='Message to send')
@click.option('--topic', default=None, help='Target topic (named persistent address). Optional.')
@click.option('--skill', default=None, help='Skill to load on the target chat. Defaults to topic for non-manager topics.')
@click.option('--chat-id', default=None, help='Target chat ID to resume (skips topic+trace lookup)')
@click.option('--work-dir', default=None, help='Working directory for the chat')
@click.option('--trace-id', default=None, help='Trace ID')
@click.option('--new', 'force_new', is_flag=True, help='Force create a new chat instead of resuming existing one')
@click.option('--from-topic', default='manager', help='Caller topic name (default: manager)')
@click.option('--from-chat-id', default=None, help='Caller chat ID (defaults to Y_CHAT_ID env var)')
@click.option('--backend', default=None, type=click.Choice(['claude_code', 'codex'], case_sensitive=False), help='Backend to use (default: claude_code)')
def notify(message: str, topic: str, skill: str, chat_id: str, work_dir: str, trace_id: str, force_new: bool, from_topic: str, from_chat_id: str, backend: str):
    """Send a message to a chat. With no flags, creates a fresh anonymous chat.

    --topic / --skill / --chat-id are independently optional:
      y notify -m "..."                    fresh anonymous chat (no topic, no skill)
      y notify --topic dev -m "..."        named-address chat; skill defaults to topic
      y notify --topic dev --skill review  named address, explicit skill override
      y notify --skill dev -m "..."        anonymous chat with dev skill loaded
      y notify --chat-id <id> -m "..."     continue an existing chat
    """
    # Default from_chat_id to Y_CHAT_ID env var
    if not from_chat_id:
        import os
        from_chat_id = os.environ.get('Y_CHAT_ID')

    payload = {
        "message": message,
        "force_new": force_new,
        "from_topic": from_topic,
    }
    if topic:
        payload["topic"] = topic
    if skill:
        payload["skill"] = skill
    if chat_id:
        payload["chat_id"] = chat_id
    if trace_id:
        payload["trace_id"] = trace_id
    if work_dir:
        payload["work_dir"] = work_dir
    if from_chat_id:
        payload["from_chat_id"] = from_chat_id
    if backend:
        payload["backend"] = backend
    try:
        resp = api_request("POST", "/api/notify", json=payload)
        data = resp.json()
        click.echo(data["chat_id"])
    except httpx.HTTPStatusError as e:
        detail = ""
        try:
            detail = e.response.json().get("detail", "")
        except Exception:
            detail = e.response.text
        click.echo(f"Error: {detail}", err=True)
        raise SystemExit(1)
