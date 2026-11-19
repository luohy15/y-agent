#!/usr/bin/env python3
"""Refuse deployment when schema, database access or referenced master keys are unavailable."""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    has_module = (root / "storage/src/storage/crypto/tenant.py").is_file()
    sys.path.insert(0, str(root / "storage/src"))
    try:
        from tenant_deploy import load_keys
        load_keys()
        from storage.crypto.guard import encrypted_row_count
        count = encrypted_row_count()
    except Exception:
        print("tenant encryption guard refused: database/schema/keys unavailable", file=sys.stderr)
        return 1
    if count and not has_module:
        print(f"refusing deploy: enc_version=1 rows={count}", file=sys.stderr)
        return 1
    print(f"tenant encryption guard ok rows={count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
