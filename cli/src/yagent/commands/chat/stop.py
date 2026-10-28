import click

from yagent.api_client import api_request


@click.command('stop')
@click.argument('chat_id')
def stop_chat(chat_id: str):
    """Stop a running chat by ID."""
    try:
        resp = api_request("POST", "/api/chat/stop", json={"chat_id": chat_id})
    except Exception as e:
        click.echo(f"Error: {e}")
        raise click.Abort() from e

    data = {}
    try:
        parsed = resp.json()
        if isinstance(parsed, dict):
            data = parsed
    except Exception:
        data = {}
    state = data.get("teardown")
    if state in ("confirmed", "not_applicable"):
        click.echo(f"Stopped chat {chat_id}")
        return
    shown = state if state else "missing"
    click.echo(
        f"Stop requested for chat {chat_id}, but session cc-{chat_id} "
        f"teardown is not confirmed ({shown}); the worker keeps retrying."
    )
    raise SystemExit(1)
