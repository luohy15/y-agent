"""`y file upload` -- copy local files and directories to the EC2 host via rsync/SSH."""

import shlex
import subprocess
from pathlib import Path

import click

from ._shared import (
    DEFAULT_DEST_ROOT,
    ensure_remote_dir,
    filter_args,
    preflight,
    resolve_target,
    rsync_flags,
    ssh_command_string,
)


def _run_source(
    source: Path,
    excludes: tuple[str, ...],
    target: str,
    ssh_opts: list[str],
    dest_root: str,
    dry_run: bool,
    mirror: bool,
    checksum: bool,
) -> int:
    destination = f"{target}:{dest_root.rstrip('/')}/"
    cmd = [
        "rsync", *rsync_flags(dry_run, mirror, checksum),
        "-e", ssh_command_string(ssh_opts),
        *filter_args(excludes),
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

    target, ssh_opts = resolve_target(host)
    preflight(target, ssh_opts)
    if not dry_run:
        ensure_remote_dir(target, ssh_opts, dest)

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
