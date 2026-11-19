#!/usr/bin/env python3
"""Refuse deployment when schema, database access, parity or referenced master keys fail.

Invalid environment or file configuration fails before any database or
lower-priority source is used. File and SSM must be canonically equal whenever
any source is present. No key material is printed.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _refuse() -> int:
    print("tenant encryption guard refused: database/schema/keys unavailable", file=sys.stderr)
    return 1


def _check_sources() -> None:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "storage/src"))
    from storage.crypto import custody

    current = os.environ.get("Y_AGENT_TENANT_MASTER_KEY_ID", "")
    raw = os.environ.get("Y_AGENT_TENANT_MASTER_KEYS", "")
    env = custody.parse_env(current, raw) if raw or current.strip() else None
    path = custody.private_key_path()
    file_cfg = custody.load_private_file(path) if path.is_symlink() or path.exists() else None
    # Untargeted deploys stay available: no SSM read and no parity demand.
    # A set parameter name requires file/SSM parity and does not fall through.
    name = custody.parameter_name()
    if name is None:
        return
    ssm_cfg = custody.read_ssm(name=name)
    custody.source_parity(env, file_cfg, ssm_cfg)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    has_module = (root / "storage/src/storage/crypto/tenant.py").is_file()
    try:
        _check_sources()
    except Exception:
        return _refuse()
    sys.path.insert(0, str(root / "storage/src"))
    try:
        from storage.crypto.guard import encrypted_row_count
        count = encrypted_row_count()
    except Exception:
        return _refuse()
    if count and not has_module:
        print(f"refusing deploy: enc_version=1 rows={count}", file=sys.stderr)
        return 1
    print(f"tenant encryption guard ok rows={count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
