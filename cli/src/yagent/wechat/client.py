import base64
import secrets
import time
from urllib.parse import urlsplit

import httpx

BASE = "https://ilinkai.weixin.qq.com"
INFO = {"channel_version": "3.0.1/y-agent-1.0.0", "bot_agent": "y-agent"}
APP = {"iLink-App-Id": "bot", "iLink-App-ClientVersion": str(0x030001)}


class ProviderError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__("WeChat provider request failed")


def provider_base(url):
    parts = urlsplit(url)
    if (parts.scheme != "https" or not (parts.hostname or "").endswith(".weixin.qq.com")
            or parts.username or parts.password or parts.port not in (None, 443)
            or parts.query or parts.fragment or parts.path not in ("", "/")):
        raise ValueError("Unexpected WeChat provider host")
    return f"https://{parts.hostname}"


class Client:
    def __init__(self, http, base=BASE, token=None):
        self.http = http
        self.base = provider_base(base)
        self.token = token

    def post(self, path, body, timeout=30):
        headers = {**APP, "AuthorizationType": "ilink_bot_token",
                   "X-WECHAT-UIN": base64.b64encode(str(secrets.randbits(32)).encode()).decode()}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
            body = {**body, "base_info": INFO}
        response = self.http.post(self.base + "/ilink/bot/" + path, json=body, headers=headers, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        for key in ("errcode", "ret"):
            if data.get(key, 0):
                raise ProviderError(data[key])
        return data

    def login(self, show, pin):
        deadline = time.monotonic() + 480
        for _ in range(3):
            qr = self.post("get_bot_qrcode?bot_type=3", {"local_token_list": []})
            show(qr["qrcode_img_content"])
            params = {"qrcode": qr["qrcode"]}
            base = BASE
            while time.monotonic() < deadline:
                try:
                    response = self.http.get(base + "/ilink/bot/get_qrcode_status", headers=APP,
                                             params=params, timeout=40)
                except httpx.TransportError:
                    time.sleep(1)
                    continue
                response.raise_for_status()
                data = response.json()
                status = data["status"]
                if "need_verifycode" in status:
                    params["verify_code"] = pin()
                elif status == "confirmed":
                    data["baseurl"] = provider_base(data.get("baseurl") or BASE)
                    return data
                elif status == "binded_redirect":
                    raise ValueError("ClawBot already bound elsewhere; no credentials reused")
                elif status in {"expired", "verify_code_blocked"}:
                    break
                elif status == "scaned_but_redirect":
                    base = provider_base("https://" + data["redirect_host"])
                elif status == "scaned":
                    params.pop("verify_code", None)
                elif status != "wait":
                    raise ValueError("Unknown WeChat login state")
                time.sleep(1)
            else:
                break
        raise ValueError("QR login expired; start again")

    def send(self, row):
        self.post("sendmessage", {"msg": {
            "from_user_id": "", "to_user_id": row["peer"], "client_id": row["outbox_id"],
            "message_type": 2, "message_state": 2, "context_token": row["context_token"],
            "item_list": [{"type": 1, "text_item": {"text": row["text"]}}],
        }})
