#!/usr/bin/env python3
"""Run SAM with private tenant configuration and redact its parameter output.

Local custody file (0600, outside the checkout): JSON with `current` and
`keys` (id -> base64url 32 bytes). CI supplies the two environment variables.
Never generates keys. Never writes the map to SAM's saved configuration.
No database access: run tenant_encryption_guard.py on the DB-reachable release
host before publication; GitHub-hosted runners cannot reach the private RDS.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import sys


def load_keys() -> tuple[str, str]:
    if os.environ.get("CI") != "true":
        path = Path.home() / ".y-agent/secrets/tenant-master-key"
        if path.exists():
            if path.is_symlink() or path.resolve().is_relative_to(Path(__file__).resolve().parents[1]):
                raise ValueError("private file must be outside checkout")
            with path.open() as handle:
                info = os.fstat(handle.fileno())
                if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.getuid():
                    raise ValueError("private file required")
                config = json.load(handle)
            os.environ["Y_AGENT_TENANT_MASTER_KEYS"] = json.dumps(config["keys"], separators=(",", ":"))
            os.environ["Y_AGENT_TENANT_MASTER_KEY_ID"] = config["current"]
    from storage.crypto.tenant import master_keys
    current, keys = master_keys()
    # IDs are also embedded in SAM's parameter grammar, not just JSON.
    if any(not key_id.replace("-", "").replace("_", "").isalnum() for key_id in keys):
        raise ValueError("invalid key id")
    return current, os.environ.get("Y_AGENT_TENANT_MASTER_KEYS", "")


def main() -> int:
    try:
        current, raw = load_keys()
    except Exception:
        print("Tenant deploy refused: private key configuration failed.", file=sys.stderr)
        return 1
    args = sys.argv[1:]
    if not args or args[0] != "deploy" or "--guided" in args or "--save-params" in args:
        print("Use a configured, non-guided SAM deploy without --save-params.", file=sys.stderr)
        return 1
    if "--parameter-overrides" not in args:
        args.append("--parameter-overrides")
    # Append after the existing override values, which must be the final option.
    args.extend([f"ParameterKey=TenantMasterKeys,ParameterValue='{raw}'",
                 f"ParameterKey=TenantMasterKeyId,ParameterValue='{current}'"])
    # SAM prints resolved overrides even for NoEcho parameters. Capture its
    # output; never stream unredacted output or print exception argv.
    child_env = {**os.environ, "SAM_CLI_TELEMETRY": "0"}
    try:
        result = subprocess.run(["sam", *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                check=False, env=child_env)
    except OSError:
        print("SAM could not be started.", file=sys.stderr)
        return 1
    output = result.stdout.decode("utf-8", errors="replace")
    secrets = [raw, *json.loads(raw or "{}").values()]
    for secret in secrets:
        if secret:
            output = output.replace(secret, "[REDACTED]").replace(json.dumps(secret)[1:-1], "[REDACTED]")
    print(output, end="")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
