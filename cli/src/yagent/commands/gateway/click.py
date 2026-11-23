import json

import click

from yagent.api_client import api_request, load_auth


@click.group("gateway")
def gateway_group():
    """Send notifications and manage IM channel bindings."""


@gateway_group.command("send")
@click.option("-m", "--message", "text", required=True, help="Notification text")
@click.option("--reply-chat", default=None, help="Chat id whose reply this prompt asks for")
def gateway_send(text, reply_chat):
    """Send text through the preferred channel, falling back to the other."""
    if not text.strip():
        raise click.UsageError("Provide a non-empty --message")
    body = {"text": text}
    if reply_chat:
        body["reply_chat"] = reply_chat
    payload = api_request("POST", "/api/gateway/send", json=body).json()
    if payload.get("fallback_from"):
        click.echo(
            f"fallback from {payload['fallback_from']} to {payload.get('channel')}",
            err=True,
        )
    click.echo(f"sent via {payload.get('channel')}")


@gateway_group.command("config")
@click.option(
    "--channel",
    required=True,
    type=click.Choice(["wechat", "telegram", "default"]),
    help="wechat, telegram, or default (unset; telegram)",
)
def gateway_config(channel):
    """Set or clear the notification channel preference."""
    payload = api_request("PUT", "/api/gateway/config", json={"channel": channel}).json()
    click.echo(payload.get("preference", channel))


@gateway_group.command("status")
def gateway_status():
    """Show the preference and which channels can deliver."""
    payload = api_request("GET", "/api/gateway/status").json()
    availability = payload.get("availability") or {}
    order = payload.get("order") or []
    click.echo(f"preference: {payload.get('preference')}")
    click.echo(f"stored: {payload.get('stored')}")
    click.echo(f"wechat: {'available' if availability.get('wechat') else 'unavailable'}")
    click.echo(f"telegram: {'available' if availability.get('telegram') else 'unavailable'}")
    click.echo(f"order: {', '.join(order) if order else 'none'}")


@gateway_group.group("channels")
def channels_group():
    """Inspect, bind, or unbind your IM channels."""


_CHANNEL = click.Choice(("telegram", "wechat"))


@channels_group.command("status")
@click.option("--json", "as_json", is_flag=True, help="Print the complete channel inventory as JSON.")
def channels_status(as_json):
    """Show bindings, channel health, and notification preference."""
    payload = api_request("GET", "/api/gateway/channels").json()
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False))
        return
    for row in payload["channels"]:
        click.echo(f"{row['channel']}: {row['health']}  peer={row['peer'] or '-'}")
        if row["channel"] == "wechat" and row["supported"]:
            for key in ("account", "heartbeat_age_seconds", "last_poll_age_seconds", "last_error", "outbox"):
                if row.get(key) is not None:
                    click.echo(f"  {key}: {row[key]}")
    notify = payload["notify"]
    click.echo(f"preference: {notify['preference']}  order: {', '.join(notify['order']) or 'none'}")


@channels_group.command("bind")
@click.argument("channel", type=_CHANNEL)
def channels_bind(channel):
    """Print the existing bind step. Use the Telegram command only in the bot's private DM."""
    if channel == "wechat":
        click.echo("y wechat login")
        return
    try:
        auth = load_auth()
    except (OSError, ValueError):
        raise click.ClickException("No usable saved login. Run 'y login' first.") from None
    token = auth.get("token") if isinstance(auth, dict) else None
    if not isinstance(token, str) or not token.strip():
        raise click.ClickException("Not logged in. Run 'y login' first.")
    click.echo(f"/bind {token}")


@channels_group.command("unbind")
@click.argument("channel", type=_CHANNEL)
@click.option("--yes", is_flag=True, help="Skip confirmation.")
def channels_unbind(channel, yes):
    """Remove a binding. WeChat unbind revokes the bridge and clears its outbox."""
    prompt = ("Unbind WeChat, revoke the bridge and peer, and clear the outbox?"
              if channel == "wechat" else "Unbind Telegram from this account?")
    if not yes:
        click.confirm(prompt, abort=True)
    api_request("POST", f"/api/gateway/channels/{channel}/unbind")
    click.echo(f"Unbound {channel}.")
