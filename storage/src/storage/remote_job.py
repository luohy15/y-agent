"""Pure validation and report policy for the bounded Mac operation."""

import re
from urllib.parse import urlsplit
from uuid import UUID

TERMINAL = frozenset({'completed', 'failed', 'cancelled', 'timeout', 'host_offline'})
FEED_URL = 'https://www.xiaohongshu.com/explore'
MAX_BYTES = 65536


def job_uuid(value):
    parsed = str(UUID(value))
    if parsed != value:
        raise ValueError('InvalidJobId')
    return parsed


def validate_payload(payload):
    if not isinstance(payload, dict) or len(payload) != 1:
        raise ValueError('InvalidPayload')
    if set(payload) == {'feed_url'} and payload['feed_url'] == FEED_URL:
        return payload
    if set(payload) != {'url'}:
        raise ValueError('InvalidPayload')
    url = payload['url']
    if not isinstance(url, str) or len(url) > 4096 or any(ord(c) < 33 for c in url):
        raise ValueError('InvalidURL')
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname not in
            {'xiaohongshu.com', 'www.xiaohongshu.com', 'xhslink.com', 'www.xhslink.com'}
            or parsed.username is not None or parsed.password is not None
            or parsed.port not in (None, 443) or '\\' in url):
        raise ValueError('InvalidURL')
    return payload


def validate_target(target):
    expected = {'target_id': 'mac', 'transport_kind': 'ssh_alias', 'transport_ref': 'mac',
                'platform': 'macos', 'executors': ['codex'], 'operations': ['browser_open']}
    if any(target.get(key) != value for key, value in expected.items()):
        raise ValueError('OperationNotAllowed')
    return target


def redact(value):
    if isinstance(value, dict):
        return {k: '[redacted]' if re.search(r'token|password|secret|authorization|cookie|api.?key', k, re.I)
                else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if not isinstance(value, str):
        return value
    value = re.sub(r'(?i)(xsec_token(?:=|%3d|["\s:]+))[^&\s"\\<>]+', r'\1[redacted]', value)
    value = re.sub(r'sk-[A-Za-z0-9_-]+', '[redacted]', value)
    value = re.sub(r'eyJ[A-Za-z0-9_.=-]+', '[redacted]', value)
    value = re.sub(r'(?i)((?:authorization|password|api[_-]?key|secret|access_token)\s*[:=]\s*)\S+',
                   r'\1[redacted]', value)
    return value
