"""`y file download` -- pull files and directories from the EC2 host via rsync/SSH."""

import shlex
import subprocess
from pathlib import Path

import click

from ._shared import (
    filter_args,
    preflight,
    resolve_target,
    rsync_flags,
    ssh_command_string,
)


def _run_source(
    source: str,
    excludes: tuple[str, ...],
    target: str,
    ssh_opts: list[str],
    dest_dir: Path,
    dry_run: bool,
    mirror: bool,
    checksum: bool,
) -> int:
    origin = f"{target}:{source}"
    destination = f"{dest_dir}/"
    cmd = [
        "rsync", *rsync_flags(dry_run, mirror, checksum),
        "-e", ssh_command_string(ssh_opts),
        *filter_args(excludes),
        origin, destination,
    ]

    click.echo(f"\n↓ {source}: {origin} -> {destination}")
    click.echo("  $ " + " ".join(shlex.quote(argument) for argument in cmd))
    return subprocess.run(cmd).returncode


@click.command("download")
@click.argument("sources", nargs=-1, metavar="SOURCE...")
@click.option("--host", default=None, help="Override EC2 target (user@host or SSH alias); default: VmConfig 'default'")
@click.option("--dest", default=".", show_default=True, help="Local destination directory")
@click.option("-n", "--dry-run", is_flag=True, help="Show what would transfer, transfer nothing")
@click.option("--mirror", is_flag=True, help="Pass rsync --delete (true mirror; off by default)")
@click.option("--checksum", is_flag=True, help="Content-verify pass (slower)")
@click.option("--exclude", "excludes", multiple=True, help="Pass a repeatable exclude pattern to rsync")
def download(sources, host, dest, dry_run, mirror, checksum, excludes):
    """Pull one or more remote files or directories from the EC2 host via rsync.

    Each SOURCE is a path on the EC2 host resolved through the API's default
    VmConfig (use --host to override it). Sources are synced into DEST on this
    machine while preserving basenames, mirroring `y file upload`.
    """
    if not sources:
        raise click.UsageError(
            "Missing argument 'SOURCE...'. Provide one or more remote file or directory paths."
        )

    dest_dir = Path(dest).expanduser()

    target, ssh_opts = resolve_target(host)
    preflight(target, ssh_opts)
    if not dry_run:
        dest_dir.mkdir(parents=True, exist_ok=True)

    summary = ", ".join(sources)
    click.echo(f"Target: {target}   Dest: {dest_dir}")
    click.echo(f"Sources: {summary}" + ("  (dry-run)" if dry_run else ""))

    failures = []
    for source in sources:
        if _run_source(source, excludes, target, ssh_opts, dest_dir, dry_run, mirror, checksum) != 0:
            failures.append(source)

    click.echo("\n" + "=" * 60)
    status = "DRY-RUN complete (nothing transferred)" if dry_run else "done"
    click.echo(f"Download {status}. Sources: {summary}")

    if failures:
        raise click.ClickException(f"rsync failed for: {', '.join(failures)}")
