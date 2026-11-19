"""Private-file and SSM custody for the tenant master key.

The loader never prints key material. A source that exists but is invalid
raises; callers must not continue to a lower-priority source.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
from pathlib import Path

from storage.crypto.tenant import TenantCryptoError

PRODUCTION_PARAMETER = "/y-agent/tenant/master-key"
PARAMETER_ENV = "Y_AGENT_TENANT_MASTER_KEY_PARAMETER"
_REGION = "us-east-1"


def private_key_path() -> Path:
    return Path.home() / ".y-agent" / "secrets" / "tenant-master-key"


def checkout_roots() -> list[Path]:
    roots = []
    seeds = [Path.cwd(), Path(__file__).resolve()]
    for seed in seeds:
        for parent in (seed, *seed.parents):
            if (parent / "template.yaml").is_file() and (parent / "storage").is_dir():
                resolved = parent.resolve()
                if resolved not in roots:
                    roots.append(resolved)
                break
    return roots


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _invalid() -> TenantCryptoError:
    return TenantCryptoError("tenant_master_key_config_invalid")


def parse_key_map(raw_keys, current: str) -> tuple[str, dict[str, bytes]]:
    """Validate one key map. ``current`` must name a 32-byte base64url key."""
    try:
        if not isinstance(raw_keys, dict) or not raw_keys or not isinstance(current, str):
            raise ValueError()
        current = current.strip()
        if not current:
            raise ValueError()
        keys = {}
        for key_id, value in raw_keys.items():
            if not isinstance(key_id, str) or not key_id or len(key_id) > 128:
                raise ValueError()
            if not isinstance(value, str) or not value:
                raise ValueError()
            if any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_="
                   for char in value):
                raise ValueError()
            key = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
            if len(key) != 32:
                raise ValueError()
            keys[key_id] = key
        if current not in keys:
            raise ValueError()
    except TenantCryptoError:
        raise
    except Exception:
        raise _invalid() from None
    return current, keys


def parse_bundle(payload) -> tuple[str, dict[str, bytes]]:
    if not isinstance(payload, dict):
        raise _invalid()
    return parse_key_map(payload.get("keys"), payload.get("current") if isinstance(payload.get("current"), str) else "")


def parse_env(current: str, raw: str) -> tuple[str, dict[str, bytes]]:
    try:
        values = json.loads(raw)
    except Exception:
        raise _invalid() from None
    return parse_key_map(values, current)


def canonical_body(current: str, keys: dict[str, bytes]) -> str:
    return json.dumps(
        {"current": current, "keys": {key_id: _b64e(material) for key_id, material in keys.items()}},
        sort_keys=True, separators=(",", ":"),
    )


def canonical_digest(current: str, keys: dict[str, bytes]) -> str:
    return hashlib.sha256(canonical_body(current, keys).encode("utf-8")).hexdigest()


def parameter_name() -> str | None:
    """Empty means untargeted: callers must not read or write SSM."""
    raw = os.environ.get(PARAMETER_ENV, "").strip()
    if not raw:
        return None
    if not _parameter_name_ok(raw):
        raise _invalid()
    return raw


def _parameter_name_ok(name: str) -> bool:
    if not name.startswith("/") or name.endswith("/") or "//" in name or len(name) > 256:
        return False
    return all(char.isalnum() or char in "/_.-" for char in name)


def nonproduction_stack(stack: str) -> bool:
    return stack.startswith("y-agent-test")


def assert_production_copy(*, target: str, stack: str, parameter: str) -> None:
    """Refuse every copy that is not an explicit production write of the one path."""
    if target != "production" or nonproduction_stack(stack) or parameter != PRODUCTION_PARAMETER:
        raise _invalid()


def assert_key_superset(existing: tuple[str, dict[str, bytes]], new: tuple[str, dict[str, bytes]]) -> None:
    """An existing id must remain, with the same bytes. New ids may be added."""
    old_keys = existing[1]
    new_keys = new[1]
    if not set(old_keys).issubset(new_keys):
        raise _invalid()
    for key_id, material in old_keys.items():
        if new_keys[key_id] != material:
            raise _invalid()


def source_parity(env, file_cfg, ssm_cfg) -> None:
    """Dormant when every source is absent. Otherwise file and SSM must match.

    A present env map must match that same canonical map. Invalid maps never
    reach here; the caller raises before trying a lower-priority source.
    """
    if env is None and file_cfg is None and ssm_cfg is None:
        return
    if file_cfg is None or ssm_cfg is None:
        raise TenantCryptoError("tenant_key_parity_mismatch")
    file_digest = canonical_digest(*file_cfg)
    if file_digest != canonical_digest(*ssm_cfg):
        raise TenantCryptoError("tenant_key_parity_mismatch")
    if env is not None and canonical_digest(*env) != file_digest:
        raise TenantCryptoError("tenant_key_parity_mismatch")


def load_private_file(path: Path | None = None) -> tuple[str, dict[str, bytes]] | None:
    """Return None only when the path is absent. Invalid files raise."""
    path = Path(path) if path is not None else private_key_path()
    if path.is_symlink():
        raise _invalid()
    if not path.exists():
        return None
    fd = -1
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_uid != os.getuid()):
            raise _invalid()
        resolved = path.resolve()
        for root in checkout_roots():
            if resolved == root or root in resolved.parents:
                raise _invalid()
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            fd = -1
            try:
                payload = json.load(handle)
            except json.JSONDecodeError:
                raise _invalid() from None
    except TenantCryptoError:
        raise
    except OSError:
        raise _invalid() from None
    finally:
        if fd >= 0:
            os.close(fd)
    return parse_bundle(payload)


def file_stamp(path: Path) -> tuple:
    info = path.lstat()
    return ("file", str(path), info.st_ino, info.st_mtime_ns, info.st_size, stat.S_IMODE(info.st_mode))


def read_ssm(client=None, name: str = PRODUCTION_PARAMETER) -> tuple[str, dict[str, bytes]] | None:
    """Return None when the parameter is absent. Other failures stay closed."""
    try:
        if client is None:
            import boto3
            region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or _REGION
            client = boto3.client("ssm", region_name=region)
        from botocore.exceptions import ClientError
        try:
            response = client.get_parameter(Name=name, WithDecryption=True)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code") if isinstance(getattr(exc, "response", None), dict) else None
            if code == "ParameterNotFound":
                return None
            raise TenantCryptoError("tenant_master_key_unavailable") from None
    except TenantCryptoError:
        raise
    except Exception:
        raise TenantCryptoError("tenant_master_key_unavailable") from None
    parameter = response.get("Parameter") if isinstance(response, dict) else None
    if not isinstance(parameter, dict) or parameter.get("Type") != "SecureString":
        raise _invalid()
    try:
        payload = json.loads(parameter.get("Value"))
    except Exception:
        raise _invalid() from None
    return parse_bundle(payload)


def copy_to_ssm(client, loaded: tuple[str, dict[str, bytes]], *, target: str, stack: str,
                 parameter: str) -> None:
    """Write only the production path. Never replace or drop an existing key id."""
    assert_production_copy(target=target, stack=stack, parameter=parameter)
    existing = read_ssm(client, parameter)
    if existing is not None:
        assert_key_superset(existing, loaded)
    current, keys = loaded
    client.put_parameter(
        Name=parameter, Value=canonical_body(current, keys), Type="SecureString",
        Tier="Standard", Overwrite=True,
    )
    copied = read_ssm(client, parameter)
    source_parity(None, loaded, copied)
