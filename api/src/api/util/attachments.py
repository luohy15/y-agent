import errno
import os
import re
import shlex
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from loguru import logger

ATTACHMENTS_DIR = Path(os.environ.get(
    "Y_AGENT_ATTACHMENTS_DIR", "/Users/roy/luohy15/assets/attachments",
))
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
DENIED_EXTENSIONS = {
    ".exe", ".msi", ".msix", ".dll", ".so", ".dylib", ".com", ".scr",
    ".bat", ".cmd", ".ps1", ".apk", ".app", ".pkg", ".deb", ".rpm",
    ".dmg", ".iso", ".jar",
}

_SSH_POOL = None


def _get_ssh_pool():
    global _SSH_POOL
    if _SSH_POOL is None:
        from agent.ssh_pool import SSHPool
        _SSH_POOL = SSHPool()
    return _SSH_POOL


def _document_size(document: dict) -> int | None:
    size = document.get("file_size")
    if isinstance(size, bool) or not isinstance(size, (int, float)):
        return None
    return int(size)


def _document_suffix(file_name: str) -> str:
    return Path(Path(file_name or "").name).suffix.lower()


def classify_document(document) -> str | None:
    """Return a rejection code, or None when the document may be stored.

    `too_large` is the 20 MB Telegram bot download cap. `unsupported_type` is
    the executable/installer denylist. Missing size or name is not a rejection:
    the downloaded-byte check still applies later.
    """
    if not isinstance(document, dict):
        return "unsupported_type"
    if (_document_size(document) or 0) > MAX_ATTACHMENT_BYTES:
        return "too_large"
    if _document_suffix(str(document.get("file_name") or "")) in DENIED_EXTENSIONS:
        return "unsupported_type"
    return None


def _safe_suffix(filename: str) -> str:
    suffix = _document_suffix(filename)
    if suffix in DENIED_EXTENSIONS or not re.fullmatch(r"\.[A-Za-z0-9]+", suffix or ""):
        return ""
    return suffix


def _attachment_name(filename: str, *, fallback_stem: str) -> str:
    stem = Path(Path(filename or "").name).stem
    safe_stem = re.sub(r"[^A-Za-z0-9._-]", "-", stem).strip(".-")
    if not safe_stem:
        safe_stem = re.sub(r"[^A-Za-z0-9._-]", "-", fallback_stem).strip(".-") or "file"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%f")[:-3] + "Z"
    return f"{safe_stem}-{timestamp}-{uuid4().hex[:8]}{_safe_suffix(filename)}"


def ssh_put_attachment_bytes(content: bytes, *, filename: str, prefix: str, vm_config) -> str:
    if len(content) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(status_code=400, detail="attachment exceeds 20 MB")
    if vm_config is None or not getattr(vm_config, "vm_name", None) or not getattr(vm_config, "api_token", None):
        raise HTTPException(status_code=503, detail="vm_config with SSH credentials is required to store attachment bytes")

    attachment_name = _attachment_name(filename, fallback_stem=prefix)
    assets_dir = ATTACHMENTS_DIR.expanduser().resolve()
    attachment_path = assets_dir / attachment_name
    sftp = None
    try:
        from agent.ec2_wake import ensure_and_touch_vm
        ensure_and_touch_vm(vm_config)
        client = _get_ssh_pool().get_or_create(vm_config)
        client.exec_command(f"mkdir -p {shlex.quote(str(assets_dir))}")
        sftp = client.open_sftp()
        with sftp.open(str(attachment_path), "wb") as remote_file:
            remote_file.write(content)
        return str(attachment_path)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("ssh attachment upload failed: {}", exc)
        raise HTTPException(status_code=503, detail="failed to store attachment on EC2; retry after VM is reachable") from exc
    finally:
        if sftp is not None:
            try:
                sftp.close()
            except Exception:
                pass


def save_attachment_bytes(content: bytes, filename: str, *, prefix: str, vm_config=None) -> str:
    """Write bytes under the attachments dir. Local first, SSH-push on a read-only FS."""
    if len(content) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(status_code=400, detail="attachment exceeds 20 MB")
    if _document_suffix(filename) in DENIED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="unsupported attachment type")

    attachment_name = _attachment_name(filename, fallback_stem=prefix)
    assets_dir = ATTACHMENTS_DIR.expanduser().resolve()
    try:
        assets_dir.mkdir(parents=True, exist_ok=True)
        attachment_path = assets_dir / attachment_name
        attachment_path.write_bytes(content)
        return str(attachment_path)
    except OSError as exc:
        if exc.errno not in (errno.EROFS, errno.EACCES, errno.EPERM):
            raise

    return ssh_put_attachment_bytes(
        content, filename=filename, prefix=prefix, vm_config=vm_config,
    )
