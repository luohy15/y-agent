import json
import time
from pathlib import Path
from urllib.parse import urlsplit

import click
import httpx
import qrcode

from yagent.api_client import DEFAULT_WEB_URL, api_request, authenticated_request, load_auth
from yagent.wechat import bridge


@click.group("wechat")
def wechat_group():
    """Bind your own WeChat bot, or operate the relay bridge."""


def write_qr(value, path):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    code = qrcode.QRCode(border=2)
    code.add_data(value)
    code.make(fit=True)
    image = code.make_image()
    image.save(path, format="PNG")
    path.chmod(0o600)
    click.echo(path)


def saved_login():
    try:
        auth = load_auth()
    except (ValueError, OSError):
        raise click.ClickException("No usable saved login. Run 'y login' first.") from None
    token = auth.get("token") if isinstance(auth, dict) else None
    if not isinstance(token, str) or not token.strip():
        raise click.ClickException("Not logged in. Run 'y login' first.")
    api = auth.get("web_url", DEFAULT_WEB_URL).rstrip("/")
    if urlsplit(api).scheme != "https":
        raise click.ClickException("WeChat binding requires an HTTPS y-agent API")
    return api, token


def _call(api, token, method, path, **kwargs):
    try:
        return authenticated_request(api, token, method, path, timeout=30, **kwargs)
    except httpx.HTTPStatusError as exc:
        raise click.ClickException(str(exc)) from None


def bind_session():
    api, token = saved_login()
    image = Path.home() / ".y-agent" / "wechat" / "bind.png"
    session_id = None
    done = False
    try:
        started = _call(api, token, "POST", "/api/wechat/bind/start", json={}).json()
        session_id = started["session_id"]
        write_qr(started["qrcode"], image)
        deadline = time.monotonic() + 480
        pin = None
        while time.monotonic() < deadline:
            body = {"session_id": session_id}
            if pin:
                body["pin"] = pin
                pin = None
            result = _call(api, token, "POST", "/api/wechat/bind/poll", json=body).json()
            status = result.get("status")
            if status == "need_verifycode":
                pin = click.prompt("WeChat PIN", hide_input=True)
                continue
            if status == "confirmed":
                if any(key in result for key in ("bot_token", "bridge_token")):
                    raise click.ClickException("Binding response included a bot credential")
                click.echo(f"DM this code within 10 minutes: {result['code']}")
                done = True
                return
            if status in {"wait", "scaned"}:
                time.sleep(1)
                continue
            raise click.ClickException(result.get("detail") or "Binding stopped")
        raise click.ClickException("QR login expired; start again")
    except ValueError as exc:
        raise click.ClickException(str(exc) or "Binding stopped") from None
    except (httpx.HTTPError, OSError, KeyError):
        raise click.ClickException("Binding failed; check account and network, then retry") from None
    finally:
        image.unlink(missing_ok=True)
        if session_id and not done:
            try:
                _call(api, token, "POST", "/api/wechat/bind/cancel", json={"session_id": session_id})
            except (click.ClickException, httpx.HTTPError, OSError):
                pass


@wechat_group.command()
def login():
    """Bind this login's own WeChat (alias of bind)."""
    bind_session()


@wechat_group.command()
def bind():
    """Bind this login's own WeChat bot. The bot token stays on the API side."""
    bind_session()


@wechat_group.command("bridge")
@click.option("--bot", default="default", show_default=True)
def run_bridge(bot):
    """Run the relay poller for every active account (reads bridge env config)."""
    try:
        bridge.run(bridge.state_path(bot))
    except (OSError, ValueError, KeyError):
        raise click.ClickException("Bridge stopped: check binding, state permissions and concurrent processes") from None


@wechat_group.command()
def status():
    click.echo(json.dumps(api_request("GET", "/api/wechat/status").json()))


@wechat_group.command()
def peers():
    """List the peers on your own bot. No message bodies."""
    click.echo(json.dumps(api_request("GET", "/api/wechat/peers").json()))


@wechat_group.command()
def unbind():
    click.echo(json.dumps(api_request("POST", "/api/wechat/unbind").json()))


@wechat_group.command()
@click.argument("peer")
def revoke(peer):
    """Revoke one of your own peers."""
    click.echo(json.dumps(api_request("POST", "/api/wechat/revoke", json={"peer": peer}).json()))


@wechat_group.command()
@click.argument("text")
def send(text):
    api_request("POST", "/api/wechat/send", json={"text": text})
    click.echo("Queued")
