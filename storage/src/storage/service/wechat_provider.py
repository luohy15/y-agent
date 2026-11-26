import base64
import secrets
from urllib.parse import urlsplit

import httpx

BASE = "https://ilinkai.weixin.qq.com"
INFO = {"channel_version": "3.0.1/y-agent-1.0.0", "bot_agent": "y-agent"}
APP = {"iLink-App-Id": "bot", "iLink-App-ClientVersion": str(0x030001)}
QR_TIMEOUT = 10


class ProviderError(Exception):
    def __init__(self, code="provider_failed"):
        self.code = code
        super().__init__("WeChat provider request failed")


def provider_base(url):
    parts = urlsplit(url or "")
    host = parts.hostname or ""
    if (parts.scheme != "https" or not host.endswith(".weixin.qq.com")
            or parts.username or parts.password or parts.port not in (None, 443)
            or parts.query or parts.fragment or parts.path not in ("", "/")):
        raise ValueError("Unexpected WeChat provider host")
    return f"https://{host}"


def interpret_status(data, base):
    """Map one provider QR status body. No network."""
    status = data.get("status") if isinstance(data, dict) else None
    if not isinstance(status, str):
        return {"state": "unknown", "base": base}
    if "need_verifycode" in status:
        return {"state": "need_verifycode", "base": base}
    if status == "confirmed":
        try:
            confirmed = provider_base(data.get("baseurl") or base)
        except ValueError:
            return {"state": "unknown", "base": base}
        return {"state": "confirmed", "base": confirmed, "baseurl": confirmed,
                "account": data.get("ilink_bot_id") or "", "peer": data.get("ilink_user_id") or "",
                "bot_token": data.get("bot_token") or ""}
    if status == "binded_redirect":
        return {"state": "binded_redirect", "base": base}
    if status in {"expired", "verify_code_blocked", "wait", "scaned"}:
        return {"state": status, "base": base}
    if status == "scaned_but_redirect":
        try:
            redirected = provider_base("https://" + (data.get("redirect_host") or ""))
        except ValueError:
            return {"state": "unknown", "base": base}
        return {"state": "scaned_but_redirect", "base": redirected}
    return {"state": "unknown", "base": base}


def _headers():
    return {**APP, "AuthorizationType": "ilink_bot_token",
            "X-WECHAT-UIN": base64.b64encode(str(secrets.randbits(32)).encode()).decode()}


def qr_start(base=BASE, local_tokens=()):
    """One provider QR request, bounded by QR_TIMEOUT."""
    with httpx.Client(follow_redirects=False, timeout=QR_TIMEOUT) as http:
        response = http.post(provider_base(base) + "/ilink/bot/get_bot_qrcode?bot_type=3",
                             json={"local_token_list": list(local_tokens)}, headers=_headers())
        response.raise_for_status()
        data = response.json()
    for key in ("errcode", "ret"):
        if data.get(key, 0):
            raise ProviderError(data[key])
    if not data.get("qrcode") or not data.get("qrcode_img_content"):
        raise ProviderError("qr_incomplete")
    return {"qrcode": data["qrcode"], "image": data["qrcode_img_content"], "base": provider_base(base)}


def qr_status(qrcode, base, pin=None):
    """One QR status read, bounded by QR_TIMEOUT. Timeout stays on wait."""
    normalized = provider_base(base)
    params = {"qrcode": qrcode}
    if pin:
        params["verify_code"] = pin
    try:
        with httpx.Client(follow_redirects=False, timeout=QR_TIMEOUT) as http:
            response = http.get(normalized + "/ilink/bot/get_qrcode_status",
                                headers=APP, params=params)
            response.raise_for_status()
            data = response.json()
    except httpx.TimeoutException:
        return {"state": "wait", "base": normalized}
    except httpx.HTTPError:
        return {"state": "provider_error", "base": normalized}
    return interpret_status(data, normalized)
