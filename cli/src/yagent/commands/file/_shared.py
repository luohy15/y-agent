"""Shared helpers for `y file upload` / `y file download` (rsync over SSH).

Both directions resolve the same EC2 target, run the same preflight, and build
rsync flags identically; keeping this in one module prevents the two verbs
from drifting on these hard-won edge cases (tilde-safe remote mkdir, BatchMode
preflight, API host resolution).
"""

import shlex
import shutil
import subprocess
from typing import List, Optional

import click

from agent.claude_code import _parse_ssh_target
from yagent.api_client import api_request

DEFAULT_DEST_ROOT = "~/luohy15/backup/mac"


def resolve_target(host_override: Optional[str]):
    """Return (ssh_target, extra_ssh_opts)."""
    if host_override:
        return host_override, []

    configs = api_request("GET", "/api/vm-config/list").json()
    vm_name = next(
        (config.get("vm_name") for config in configs if config.get("name") == "default"), None
    )
    if not vm_name:
        raise click.ClickException(
            "No default VM config found. Pass --host <user@host-or-alias>."
        )
    user, host, port = _parse_ssh_target(vm_name)
    target = f"{user}@{host}" if user else host
    extra_opts = [] if port == 22 else ["-p", str(port)]
    return target, extra_opts


def preflight(target: str, ssh_opts: List[str]):
    if shutil.which("rsync") is None:
        raise click.ClickException(
            "rsync not found on PATH. macOS ships one by default; install a newer "
            "one with `brew install rsync` if needed, then retry."
        )

    ssh_cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", *ssh_opts, target, "true"]
    try:
        result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=20)
    except subprocess.TimeoutExpired:
        raise click.ClickException(f"SSH preflight to {target} timed out.")
    if result.returncode != 0:
        raise click.ClickException(
            f"Cannot reach {target} non-interactively via SSH (exit {result.returncode}).\n"
            f"{result.stderr.strip()}\n"
            "Make sure your SSH key/agent is set up (ssh-add, ~/.ssh/config) and retry."
        )


def ensure_remote_dir(target: str, ssh_opts: List[str], remote_dir: str):
    if remote_dir.startswith("~/"):
        quoted = "~/" + shlex.quote(remote_dir[2:])
    elif remote_dir == "~":
        quoted = "~"
    else:
        quoted = shlex.quote(remote_dir)
    ssh_cmd = ["ssh", *ssh_opts, target, f"mkdir -p {quoted}"]
    result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=20)
    if result.returncode != 0:
        raise click.ClickException(
            f"Failed to create remote dir {remote_dir}: {result.stderr.strip()}"
        )


def rsync_flags(dry_run: bool, mirror: bool, checksum: bool) -> List[str]:
    flags = ["-a", "--compress", "--partial", "--info=progress2", "--human-readable"]
    if dry_run:
        flags.append("--dry-run")
    if mirror:
        flags.append("--delete")
    if checksum:
        flags.append("--checksum")
    return flags


def ssh_command_string(ssh_opts: List[str]) -> str:
    return " ".join(["ssh", *ssh_opts]) if ssh_opts else "ssh"


def filter_args(excludes: tuple) -> List[str]:
    return [argument for pattern in excludes for argument in ("--exclude", pattern)]
