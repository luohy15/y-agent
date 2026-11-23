import json
from urllib.parse import urlsplit

import click
import httpx
import qrcode

from yagent.api_client import api_request, resolve_api_auth
from yagent.wechat import bridge
from yagent.wechat.client import Client, ProviderError


@click.group("wechat")
def wechat_group():
    """Bind and operate the maintainer's WeChat DMs."""


def qr(value):
    image = qrcode.QRCode(border=2)
    image.add_data(value)
    image.print_ascii(invert=True)


@wechat_group.command()
@click.option("--user", required=True)
@click.option("--bot", default="default", show_default=True)
def login(user, bot):
    """On the default node, scan the QR then send the one-time code."""
    api, _ = resolve_api_auth()
    if urlsplit(api).scheme != "https":
        raise click.ClickException("Login requires an HTTPS y-agent API")
    try:
        path = bridge.state_path(bot)
        with bridge.exclusive(path), httpx.Client(follow_redirects=False) as http:
            api_request("GET", "/api/wechat/status", params={"email": user})
            result = Client(http).login(qr, lambda: click.prompt("WeChat PIN", hide_input=True))
            bound = api_request("POST", "/api/wechat/bind/complete", json={
                "email": user, "account": result["ilink_bot_id"], "peer": result["ilink_user_id"],
                "bot_token": result["bot_token"],
            }).json()
            bridge.save(path, {"api": api, "bridge_token": bound["bridge_token"],
                               "ilink_bot_id": result["ilink_bot_id"], "baseurl": result["baseurl"],
                               "bot_token": result["bot_token"], "get_updates_buf": ""})
            click.echo(f"Start y wechat bridge --bot {bot}, then DM this code within 10 minutes: {bound['code']}")
    except (httpx.HTTPError, ProviderError, KeyError):
        raise click.ClickException("Binding failed; check account and network, then retry") from None
    except ValueError as exc:
        raise click.ClickException("Login stopped: already bound, expired QR, invalid host or local state") from exc


@wechat_group.command("bridge")
@click.option("--bot", default="default", show_default=True)
def run_bridge(bot):
    try:
        bridge.run(bridge.state_path(bot))
    except (OSError, ValueError, KeyError):
        raise click.ClickException("Bridge stopped: check binding, state permissions and concurrent processes") from None


@wechat_group.command()
def status():
    click.echo(json.dumps(api_request("GET", "/api/wechat/status").json()))


@wechat_group.command()
def unbind():
    click.echo(json.dumps(api_request("POST", "/api/wechat/unbind").json()))


@wechat_group.command()
@click.argument("text")
def send(text):
    api_request("POST", "/api/wechat/send", json={"text": text})
    click.echo("Queued")
