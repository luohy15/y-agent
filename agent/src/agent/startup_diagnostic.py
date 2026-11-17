"""Bounded, credential-redacted diagnostics for detached CLI startup failures."""

import re
from typing import Optional
from loguru import logger
from agent.claude_code import _shell_quote, _ssh_exec, _stream_error_suffix

# Displayed startup diagnostics stay inside 4 KB. The reader may fetch a
# little more so the formatter can keep the useful tail.
DIAGNOSTIC_DISPLAY_BYTES = 4096
_ANSI_RE = re.compile(
    r"\x1b\[[0-?]*[ -/]*[@-~]"
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"
    r"|\x1b[@-Z\\-_]"
)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SECRET_BEARER_RE = re.compile(r"(?i)(authorization\s*:\s*bearer\s+)\S+")
_SECRET_ASSIGN_RE = re.compile(
    r"(?i)(api[_-]?key|openai_api_key|access_token|auth_token|token|secret|password)"
    r"(\s*['\"]?\s*[:=]\s*['\"]?)([^\s'\"&,}]+)"
)
_SECRET_QUERY_RE = re.compile(r"(?i)([?&](?:api[_-]?key|access_token|token|key|secret)=)[^&\s]+")
_SECRET_USERINFO_RE = re.compile(r"://[^/\s:@]+:[^/\s@]+@")
_SECRET_SK_RE = re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}\b")

def _strip_controls(text: str) -> str:
    return _CONTROL_RE.sub("", _ANSI_RE.sub("", text))


def _redact_secrets(text: str) -> str:
    text = _SECRET_BEARER_RE.sub(r"\1[redacted]", text)
    text = _SECRET_ASSIGN_RE.sub(r"\1\2[redacted]", text)
    text = _SECRET_QUERY_RE.sub(r"\1[redacted]", text)
    text = _SECRET_USERINFO_RE.sub("://[redacted]@", text)
    return _SECRET_SK_RE.sub("sk-[redacted]", text)


def _clip_bytes(text: str, limit: int) -> str:
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text
    return raw[-limit:].decode("utf-8", errors="ignore")


def interpret_exit_file(raw: Optional[str], *, unreadable: bool = False) -> tuple[Optional[int], str]:
    """Return ``(code, state)`` where state is ok, missing, invalid, or unreadable."""
    if unreadable:
        return None, "unreadable"
    if raw is None:
        return None, "missing"
    text = raw.strip()
    if not text:
        return None, "missing"
    try:
        return int(text), "ok"
    except ValueError:
        return None, "invalid"


def _exit_phrase(exit_code: Optional[int], exit_state: str) -> str:
    if exit_state in ("unreadable", "invalid"):
        return "exit status unreadable"
    if exit_state != "ok" or exit_code is None:
        return "exit status missing"
    if exit_code == 137:
        return "terminated by SIGKILL (9)"
    if exit_code == 143:
        return "terminated by SIGTERM (15)"
    return f"process exited with code {exit_code}"


def format_startup_diagnostic(
    stderr: Optional[str],
    exit_raw: Optional[str] = None,
    *,
    backend: str = "Agent",
    stderr_unreadable: bool = False,
    exit_unreadable: bool = False,
    stream_error: Optional[Exception] = None,
    exit_code: Optional[int] = None,
    exit_state: Optional[str] = None,
) -> str:
    """Bounded, redacted backend startup error. Missing stderr still names the exit."""
    if exit_code is None and exit_state is None:
        exit_code, exit_state = interpret_exit_file(exit_raw, unreadable=exit_unreadable)
    elif exit_state is None:
        exit_state = "ok" if exit_code is not None else "missing"
    header = f"{backend} exited before producing output: {_exit_phrase(exit_code, exit_state)}."
    if stderr_unreadable:
        body = "stderr unreadable."
    elif stderr is None or stderr == "":
        body = "stderr missing."
    else:
        body = _redact_secrets(_strip_controls(stderr)).strip()
        if not body:
            body = "stderr missing."
    suffix = _redact_secrets(_strip_controls(_stream_error_suffix(stream_error)))
    marker = ""
    prefix = f"{header} "
    budget = DIAGNOSTIC_DISPLAY_BYTES - len((prefix + suffix).encode("utf-8"))
    if budget < 0:
        return _clip_bytes(header + suffix, DIAGNOSTIC_DISPLAY_BYTES)
    raw_body = body.encode("utf-8")
    if len(raw_body) > budget:
        marker = "\n[truncated]"
        budget -= len(marker.encode("utf-8"))
        body = _clip_bytes(body, max(budget, 0))
    return f"{prefix}{body}{marker}{suffix}"


def _read_attempt_file(client, path: str, *, tail: bool) -> tuple[Optional[str], bool]:
    """Return ``(text, unreadable)``. ``text`` is None when the file is absent."""
    try:
        if tail:
            quoted = _shell_quote(path)
            command = f"if [ -f {quoted} ]; then tail -c 8192 {quoted}; else printf '%s' '__Y_MISSING__'; fi"
        else:
            quoted = _shell_quote(path)
            command = f"if [ -f {quoted} ]; then cat {quoted}; else printf '%s' '__Y_MISSING__'; fi"
        raw = _ssh_exec(client, command)
    except Exception as exc:
        logger.warning("backend attempt log unreadable path={} error={}", path, type(exc).__name__)
        return None, True
    if raw == "__Y_MISSING__":
        return None, False
    return raw, False


def read_attempt_diagnostic(client, chat_id: str, stream_error: Optional[Exception] = None, *, backend: str = "Agent") -> dict:
    """Read this attempt's stderr and exit file and format a bounded diagnostic."""
    stderr, stderr_unreadable = _read_attempt_file(client, f"/tmp/cc-{chat_id}.stderr", tail=True)
    exit_raw, exit_unreadable = _read_attempt_file(client, f"/tmp/cc-{chat_id}.exit", tail=False)
    exit_code, exit_state = interpret_exit_file(exit_raw, unreadable=exit_unreadable)
    text = format_startup_diagnostic(
        stderr,
        backend=backend,
        stderr_unreadable=stderr_unreadable,
        exit_code=exit_code,
        exit_state=exit_state,
        stream_error=stream_error,
    )
    return {
        "text": text,
        "stderr": None if stderr_unreadable else stderr,
        "exit_code": exit_code,
        "exit_state": exit_state,
    }
