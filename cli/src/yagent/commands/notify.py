import click

from yagent.api_client import api_request


@click.command('notify')
@click.argument('skill_name')
@click.option('--message', '-m', required=True, help='Message to send')
@click.option('--work-dir', default=None, help='Working directory for the skill')
@click.option('--trace-id', default=None, help='Trace ID')
@click.option('--new', 'force_new', is_flag=True, help='Force create a new chat instead of resuming existing one')
@click.option('--from-skill', default='DM', help='Caller skill name')
@click.option('--chat-id', default=None, help='Target chat ID to resume (skips skill+trace lookup)')
@click.option('--from-chat-id', default=None, help='Caller chat ID (defaults to Y_CHAT_ID env var)')
def notify(skill_name: str, message: str, work_dir: str, trace_id: str, force_new: bool, from_skill: str, chat_id: str, from_chat_id: str):
    """Send a message to a skill via trace-based communication."""
    # Default from_chat_id to Y_CHAT_ID env var
    if not from_chat_id:
        import os
        from_chat_id = os.environ.get('Y_CHAT_ID')

    payload = {
        "skill": skill_name,
        "message": message,
        "force_new": force_new,
        "from_skill": from_skill,
    }
    if trace_id:
        payload["trace_id"] = trace_id
    if work_dir:
        payload["work_dir"] = work_dir
    if chat_id:
        payload["chat_id"] = chat_id
    if from_chat_id:
        payload["from_chat_id"] = from_chat_id
    resp = api_request("POST", "/api/notify", json=payload)
    data = resp.json()
    click.echo(data["chat_id"])
