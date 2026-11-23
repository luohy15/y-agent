import json
from urllib.parse import urlsplit

import click
import httpx
import qrcode

from yagent.api_client import DEFAULT_WEB_URL, api_request, authenticated_request, load_auth
from yagent.wechat import bridge
from yagent.wechat.client import Client, ProviderError


@click.group("wechat")
def wechat_group():
    """Bind and operate the maintainer's WeChat DMs."""


def write_qr(value, path):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    code = qrcode.QRCode(border=2)
    code.add_data(value)
    code.make(fit=True)
    image = code.make_image()
    image.save(path, format="PNG")
    path.chmod(0o600)
    click.echo(path)


@wechat_group.command()
@click.option("--bot", default="default", show_default=True)
def login(bot):
    """Bind WeChat to the current y login on the default node."""
    try:
        auth = load_auth()
    except (ValueError, OSError):
        raise click.ClickException("No usable saved login. Run 'y login' first.") from None
    token = auth.get("token") if isinstance(auth, dict) else None
    if not isinstance(token, str) or not token.strip():
        raise click.ClickException("Not logged in. Run 'y login' first.")
    api = auth.get("web_url", DEFAULT_WEB_URL).rstrip("/")
    if urlsplit(api).scheme != "https":
        raise click.ClickException("Login requires an HTTPS y-agent API")
    try:
        path = bridge.state_path(bot)
        with bridge.exclusive(path), httpx.Client(follow_redirects=False) as http:
            authenticated_request(api, token, "GET", "/api/wechat/status")
            image = path.with_suffix(".png")
            result = Client(http).login(
                lambda value: write_qr(value, image),
                lambda: click.prompt("WeChat PIN", hide_input=True),
            )
            image.unlink(missing_ok=True)
            bound = authenticated_request(api, token, "POST", "/api/wechat/bind/complete", json={
                "account": result["ilink_bot_id"], "peer": result["ilink_user_id"],
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
