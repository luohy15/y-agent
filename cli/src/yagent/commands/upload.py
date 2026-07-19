"""`y upload` -- copy local files and directories to the EC2 host via rsync/SSH."""

import shlex
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

import click

from agent.claude_code import _parse_ssh_target
from yagent.api_client import api_request

DEFAULT_DEST_ROOT = "~/luohy15/backup/mac"


def _resolve_target(host_override: Optional[str]):
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


def _preflight(target: str, ssh_opts: List[str]):
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


def _ensure_remote_dir(target: str, ssh_opts: List[str], remote_dir: str):
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


def _rsync_flags(dry_run: bool, mirror: bool, checksum: bool) -> List[str]:
    flags = ["-a", "--compress", "--partial", "--info=progress2", "--human-readable"]
    if dry_run:
        flags.append("--dry-run")
    if mirror:
        flags.append("--delete")
    if checksum:
        flags.append("--checksum")
    return flags


def _run_source(
    source: Path,
    excludes: tuple[str, ...],
    target: str,
    ssh_opts: List[str],
    dest_root: str,
    dry_run: bool,
    mirror: bool,
    checksum: bool,
) -> int:
    ssh_command = " ".join(["ssh", *ssh_opts]) if ssh_opts else "ssh"
    filter_args = [argument for pattern in excludes for argument in ("--exclude", pattern)]
    destination = f"{target}:{dest_root.rstrip('/')}/"
    cmd = [
        "rsync", *_rsync_flags(dry_run, mirror, checksum),
        "-e", ssh_command,
        *filter_args,
        str(source), destination,
    ]

    click.echo(f"\n↑ {source.name}: {source} -> {destination}")
    click.echo("  $ " + " ".join(shlex.quote(argument) for argument in cmd))
    return subprocess.run(cmd).returncode


@click.command("upload")
@click.argument("sources", nargs=-1, metavar="SOURCE...")
@click.option("--host", default=None, help="Override EC2 target (user@host or SSH alias); default: VmConfig 'default'")
@click.option("--dest", default=DEFAULT_DEST_ROOT, show_default=True, help="Remote destination directory")
@click.option("-n", "--dry-run", is_flag=True, help="Show what would transfer, transfer nothing")
@click.option("--mirror", is_flag=True, help="Pass rsync --delete (true mirror; off by default)")
@click.option("--checksum", is_flag=True, help="Content-verify pass (slower)")
@click.option("--exclude", "excludes", multiple=True, help="Pass a repeatable exclude pattern to rsync")
def upload(sources, host, dest, dry_run, mirror, checksum, excludes):
    """Push one or more local files or directories to the EC2 host via rsync.

    Each SOURCE is expanded locally and synced beneath DEST while preserving its
    basename. The default destination is ~/luohy15/backup/mac on the EC2 host
    resolved through the API's default VmConfig. Use --host to override it.
    """
    if not sources:
        raise click.UsageError(
            "Missing argument 'SOURCE...'. Provide one or more local file or directory paths."
        )

    source_paths = [Path(source).expanduser() for source in sources]
    missing_sources = [str(source) for source in source_paths if not source.exists()]
    if missing_sources:
        raise click.ClickException(
            f"Local source does not exist: {', '.join(missing_sources)}"
        )

    target, ssh_opts = _resolve_target(host)
    _preflight(target, ssh_opts)
    if not dry_run:
        _ensure_remote_dir(target, ssh_opts, dest)

    summary = ", ".join(str(source) for source in source_paths)
    click.echo(f"Target: {target}   Dest root: {dest}")
    click.echo(f"Sources: {summary}" + ("  (dry-run)" if dry_run else ""))

    failures = []
    for source in source_paths:
        if _run_source(source, excludes, target, ssh_opts, dest, dry_run, mirror, checksum) != 0:
            failures.append(str(source))

    click.echo("\n" + "=" * 60)
    status = "DRY-RUN complete (nothing transferred)" if dry_run else "done"
    click.echo(f"Upload {status}. Sources: {summary}")

    if failures:
        raise click.ClickException(f"rsync failed for: {', '.join(failures)}")
