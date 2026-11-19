#!/usr/bin/env python3
"""Run SAM without putting the tenant master key on the command line.

`deploy` validates a present env map or private file and refuses an invalid
higher-priority source. It does not read or write SSM and does not append
tenant parameters. `sync-ssm` is the separate copy path and refuses to run
without `--confirm-ssm-copy`.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storage/src"))

from storage.crypto import custody  # noqa: E402
from storage.crypto.tenant import TenantCryptoError  # noqa: E402


def _secret_strings(config) -> list[str]:
    if config is None:
        return []
    _current, keys = config
    return [custody._b64e(material) for material in keys.values()]


def validate_local_sources():
    """Validate env, else the private file. Do not fall through and do not touch SSM."""
    current = os.environ.get("Y_AGENT_TENANT_MASTER_KEY_ID", "")
    raw = os.environ.get("Y_AGENT_TENANT_MASTER_KEYS", "")
    if raw or current.strip():
        return custody.parse_env(current, raw)
    path = custody.private_key_path()
    if path.is_symlink() or path.exists():
        loaded = custody.load_private_file(path)
        if loaded is None:
            raise TenantCryptoError("tenant_master_key_config_invalid")
        return loaded
    return None


def deploy(args: list[str]) -> int:
    try:
        config = validate_local_sources()
    except Exception:
        print("Tenant deploy refused: private key configuration failed.", file=sys.stderr)
        return 1
    if not args or args[0] != "deploy" or "--guided" in args or "--save-params" in args:
        print("Use a configured, non-guided SAM deploy without --save-params.", file=sys.stderr)
        return 1
    child_env = {**os.environ, "SAM_CLI_TELEMETRY": "0"}
    try:
        result = subprocess.run(["sam", *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                check=False, env=child_env)
    except OSError:
        print("SAM could not be started.", file=sys.stderr)
        return 1
    output = result.stdout.decode("utf-8", errors="replace")
    for secret in _secret_strings(config):
        if secret:
            output = output.replace(secret, "[REDACTED]").replace(json.dumps(secret)[1:-1], "[REDACTED]")
    print(output, end="")
    return result.returncode


def sync_ssm(args: list[str]) -> int:
    """Copy the private file to the production parameter. Refuses every other target."""
    if "--confirm-ssm-copy" not in args or "--target" not in args:
        print("SSM copy is not authorized. Refusing.", file=sys.stderr)
        return 1
    try:
        target = args[args.index("--target") + 1]
        stack = os.environ.get("Y_AGENT_STACK", "")
        configured = os.environ.get(custody.PARAMETER_ENV, "").strip()
        parameter = configured or custody.PRODUCTION_PARAMETER
        # Refuse non-production and non-production paths before reading the file or AWS.
        custody.assert_production_copy(target=target, stack=stack, parameter=parameter)
        if os.environ.get("Y_AGENT_TENANT_MASTER_KEY_ID", "").strip() or os.environ.get("Y_AGENT_TENANT_MASTER_KEYS", ""):
            raise TenantCryptoError("tenant_master_key_config_invalid")
        loaded = custody.load_private_file()
        if loaded is None:
            raise TenantCryptoError("tenant_master_key_config_invalid")
        import boto3
        region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or custody._REGION
        client = boto3.client("ssm", region_name=region)
        custody.copy_to_ssm(client, loaded, target=target, stack=stack, parameter=parameter)
    except Exception:
        print("SSM copy refused.", file=sys.stderr)
        return 1
    print("ssm copy parity ok")
    return 0


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "sync-ssm":
        return sync_ssm(sys.argv[2:])
    return deploy(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
