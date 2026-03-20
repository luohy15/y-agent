import os

import click

from yagent.api_client import api_request


@click.command('notify')
@click.argument('skill_name')
@click.option('--message', '-m', required=True, help='Message to send')
@click.option('--work-dir', default=None, help='Working directory for the skill')
@click.option('--trace-id', default=None, help='Trace ID (auto-detected from Y_TRACE_ID env)')
@click.option('--new', 'new_chat', is_flag=True, help='Force create a new chat')
@click.option('--from-chat-id', default=None, help='Caller chat ID (auto-detected from Y_CHAT_ID env)')
@click.option('--from-work-dir', default=None, help='Caller working directory')
@click.option('--from-skill', default=None, help='Caller skill name (auto-detected from Y_SKILL env)')
def notify(skill_name: str, message: str, work_dir: str, trace_id: str, new_chat: bool, from_chat_id: str, from_work_dir: str, from_skill: str):
    """Send a message to a skill via trace-based communication."""
    # Auto-detect from environment if not explicitly provided
    if not trace_id:
        trace_id = os.environ.get('Y_TRACE_ID')
    if not from_chat_id:
        from_chat_id = os.environ.get('Y_CHAT_ID')
    if not from_skill:
        from_skill = os.environ.get('Y_SKILL')

    # Try lookup from chat_id first (finds trace where this chat is last participant)
    if (not trace_id or not from_skill) and from_chat_id:
        try:
            resp = api_request("GET", "/api/trace/by-chat", params={"chat_id": from_chat_id})
            data = resp.json()
            if not trace_id:
                trace_id = data.get("trace_id")
            if not from_skill:
                from_skill = data.get("skill")
        except Exception:
            pass

    # Fallback to Y_MESSAGE_ID as trace_id (starts a new trace)
    if not trace_id:
        trace_id = os.environ.get('Y_MESSAGE_ID')

    if not trace_id:
        raise click.UsageError('--trace-id is required (or set Y_TRACE_ID env)')
    payload = {
        "skill": skill_name,
        "message": message,
        "trace_id": trace_id,
        "new_chat": new_chat,
    }
    if work_dir:
        payload["work_dir"] = work_dir
    if from_chat_id:
        payload["from_chat_id"] = from_chat_id
    if from_work_dir:
        payload["from_work_dir"] = from_work_dir
    if from_skill:
        payload["from_skill"] = from_skill

    resp = api_request("POST", "/api/notify", json=payload)
    data = resp.json()
    click.echo(data["chat_id"])
