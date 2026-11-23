import click

from yagent.api_client import api_request


@click.group("notify")
def notify_group():
    """Send a proactive notification on the configured channel."""


@notify_group.command("send")
@click.option("-m", "--message", "text", required=True, help="Notification text")
def notify_send(text):
    """Send text through the preferred channel, falling back to the other."""
    if not text.strip():
        raise click.UsageError("Provide a non-empty --message")
    payload = api_request("POST", "/api/notify/send", json={"text": text}).json()
    if payload.get("fallback_from"):
        click.echo(
            f"fallback from {payload['fallback_from']} to {payload.get('channel')}",
            err=True,
        )
    click.echo(f"sent via {payload.get('channel')}")


@notify_group.command("config")
@click.option(
    "--channel",
    required=True,
    type=click.Choice(["wechat", "telegram", "default"]),
    help="wechat, telegram, or default (unset; telegram)",
)
def notify_config(channel):
    """Set or clear the notification channel preference."""
    payload = api_request("PUT", "/api/notify/config", json={"channel": channel}).json()
    click.echo(payload.get("preference", channel))


@notify_group.command("status")
def notify_status():
    """Show the preference and which channels can deliver."""
    payload = api_request("GET", "/api/notify/status").json()
    availability = payload.get("availability") or {}
    order = payload.get("order") or []
    click.echo(f"preference: {payload.get('preference')}")
    click.echo(f"stored: {payload.get('stored')}")
    click.echo(f"wechat: {'available' if availability.get('wechat') else 'unavailable'}")
    click.echo(f"telegram: {'available' if availability.get('telegram') else 'unavailable'}")
    click.echo(f"order: {', '.join(order) if order else 'none'}")
