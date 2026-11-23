import base64
import secrets
from urllib.parse import urlsplit

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

    def send(self, row):
        self.post("sendmessage", {"msg": {
            "from_user_id": "", "to_user_id": row["peer"], "client_id": row["outbox_id"],
            "message_type": 2, "message_state": 2, "context_token": row["context_token"],
            "item_list": [{"type": 1, "text_item": {"text": row["text"]}}],
        }})
