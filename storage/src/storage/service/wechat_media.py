"""Inbound WeChat CDN media: URL validation, fetch and AES decryption.

The bridge forwards only a small descriptor. The API fetches because the
bridge-to-API body is capped at 600 KB and the Lambda request at 6 MB, while a
single file may be 20 MB; the bridge also stays credential-only with no crypto.

The provider stores media as an AES-128-ECB/PKCS7 blob on its own CDN. This is
transport of the provider's at-rest blob, not channel encryption.
"""

import asyncio
import base64
import binascii
import ipaddress
import re
import socket
from urllib.parse import quote, urlsplit

import httpx
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

CDN_HOST_SUFFIX = ".cdn.weixin.qq.com"
CDN_BASE_URL = "https://novac2c.cdn.weixin.qq.com/c2c"
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_FILE_BYTES = 20 * 1024 * 1024
_HEX_KEY = re.compile(r"[0-9a-fA-F]{32}")
_BLOCK_BYTES = 16
_CONNECT_TIMEOUT = 15
_READ_TIMEOUT = 90


class MediaRejected(ValueError):
    """A descriptor that cannot be fetched, decoded or decrypted.

    `code` is a closed machine value (`invalid_url`, `invalid_key`,
    `too_large`, `fetch_failed`, `decrypt_failed`). It never carries the URL
    or any key material.
    """

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def validate_media_url(url):
    """Prove one CDN download URL is https on the allowlisted Tencent host."""
    if not isinstance(url, str) or not url:
        raise MediaRejected("invalid_url")
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.username or parts.password:
        raise MediaRejected("invalid_url")
    try:
        port = parts.port
    except ValueError:
        raise MediaRejected("invalid_url") from None
    if port not in (None, 443):
        raise MediaRejected("invalid_url")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host or host == CDN_HOST_SUFFIX.lstrip(".") or not host.endswith(CDN_HOST_SUFFIX):
        raise MediaRejected("invalid_url")
    return host


def media_url(item):
    """The provider's own URL when present, else the documented CDN download URL."""
    if not isinstance(item, dict):
        raise MediaRejected("invalid_url")
    full_url = (item.get("full_url") or "").strip()
    if full_url:
        return full_url
    param = (item.get("encrypt_query_param") or "").strip()
    if not param:
        raise MediaRejected("invalid_url")
    return f"{CDN_BASE_URL}/download?encrypted_query_param={quote(param, safe='')}"


def is_public_ip(value):
    """True only for a globally routable address, never a private or link-local one."""
    try:
        return ipaddress.ip_address(str(value).split("%", 1)[0]).is_global
    except ValueError:
        return False


async def require_public_host(host):
    """Resolve the host and reject unless every address is public."""
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError:
        raise MediaRejected("invalid_url") from None
    addresses = {info[4][0] for info in infos if info[4]}
    if not addresses or not all(is_public_ip(address) for address in addresses):
        raise MediaRejected("invalid_url")


def decode_aes_key(item):
    """The 16-byte AES key from either spelling the provider uses.

    `aeskey` is a raw 32-character hex key (an image's preferred field). The
    base64 `aes_key` decodes either to the 16 raw bytes or to 32 hex
    characters, which is what the provider sends for files.
    """
    aeskey = (item.get("aeskey") or "").strip()
    if _HEX_KEY.fullmatch(aeskey):
        return bytes.fromhex(aeskey)
    encoded = (item.get("aes_key") or "").strip()
    if not encoded:
        raise MediaRejected("invalid_key")
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise MediaRejected("invalid_key") from None
    if len(decoded) == _BLOCK_BYTES:
        return decoded
    if len(decoded) == 2 * _BLOCK_BYTES:
        text = decoded.decode("ascii", "replace")
        if _HEX_KEY.fullmatch(text):
            return bytes.fromhex(text)
    raise MediaRejected("invalid_key")


def decrypt_media(ciphertext, key):
    """AES-128-ECB decrypt with PKCS7 unpadding."""
    if not ciphertext or len(ciphertext) % _BLOCK_BYTES:
        raise MediaRejected("decrypt_failed")
    try:
        decryptor = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
        padded = decryptor.update(ciphertext) + decryptor.finalize()
        unpadder = padding.PKCS7(_BLOCK_BYTES * 8).unpadder()
        return unpadder.update(padded) + unpadder.finalize()
    except ValueError:
        raise MediaRejected("decrypt_failed") from None


def enforce_cap(size, max_bytes):
    if size > max_bytes:
        raise MediaRejected("too_large")


async def fetch_media(item, *, max_bytes):
    """Fetch one descriptor and return its decrypted plaintext bytes."""
    url = media_url(item)
    host = validate_media_url(url)
    key = decode_aes_key(item)
    await require_public_host(host)
    timeout = httpx.Timeout(_READ_TIMEOUT, connect=_CONNECT_TIMEOUT)
    ciphertext = bytearray()
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=timeout) as client:
            async with client.stream("GET", url) as response:
                if response.status_code != 200:
                    raise MediaRejected("fetch_failed")
                length = response.headers.get("content-length", "")
                if length.isdigit():
                    enforce_cap(int(length), max_bytes + _BLOCK_BYTES)
                async for chunk in response.aiter_bytes():
                    ciphertext.extend(chunk)
                    enforce_cap(len(ciphertext), max_bytes + _BLOCK_BYTES)
    except httpx.HTTPError:
        raise MediaRejected("fetch_failed") from None
    plain = decrypt_media(bytes(ciphertext), key)
    enforce_cap(len(plain), max_bytes)
    return plain
