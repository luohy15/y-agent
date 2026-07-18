"""`y upload` -- push files from this Mac to the EC2 backup host over rsync/SSH.

Client-side command: runs on the user's Mac, shells out to the system `rsync`
over the user's own SSH setup (ssh-agent / ~/.ssh/config), and pushes named
source groups (or ad-hoc paths) to `~/luohy15/backup/mac/<group>/` on the EC2
host resolved via the API from the 'default' VmConfig (override with --host).
See todo 2826 for the design.
"""

import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import click

from agent.claude_code import _parse_ssh_target
from yagent.api_client import api_request

DEFAULT_DEST_ROOT = "~/luohy15/backup/mac"

# Ad-hoc positional source paths land under this subdir on the backup host.
ADHOC_GROUP = "misc"

# Generic build-artifact / cache dirs to skip under a code tree.
CODE_EXCLUDES = [
    "node_modules", ".venv", "venv", "__pycache__", ".next", ".nuxt",
    "dist", "build", "target", ".cache", ".turbo", ".pytest_cache",
    ".mypy_cache", ".gradle", ".terraform", ".DS_Store", "*.pyc",
]


@dataclass
class SourceGroup:
    description: str
    default_on: bool
    roots: List[str]
    excludes: List[str] = field(default_factory=list)


SOURCE_GROUPS = {
    "code": SourceGroup(
        description="~/src (all repos, excluding build artifacts / caches)",
        default_on=True,
        roots=["~/src"],
        excludes=CODE_EXCLUDES,
    ),
    "docs": SourceGroup(
        description="~/Documents",
        default_on=True,
        roots=["~/Documents"],
    ),
    "desktop": SourceGroup(
        description="~/Desktop",
        default_on=False,
        roots=["~/Desktop"],
    ),
    "downloads": SourceGroup(
        description="~/Downloads",
        default_on=False,
        roots=["~/Downloads"],
    ),
    "creds": SourceGroup(
        description="~/.ssh, ~/.aws, ~/.kube, ~/.git-credentials, ~/.config/gcloud "
                    "(EXCLUDED by default -- requires --include-creds)",
        default_on=False,
        roots=["~/.ssh", "~/.aws", "~/.kube", "~/.git-credentials", "~/.config/gcloud"],
    ),
}

DEFAULT_GROUPS = [name for name, g in SOURCE_GROUPS.items() if g.default_on]


def _print_group_table():
    click.echo(f"{'Group':<10} {'Default':<10} Sources")
    for name, group in SOURCE_GROUPS.items():
        if name == "creds":
            default = "EXCLUDED"
        else:
            default = "yes" if group.default_on else "opt-in"
        click.echo(f"{name:<10} {default:<10} {group.description}")
    click.echo(
        f"\nAd-hoc: any token containing '/' or starting with '~' or '.' is treated "
        f"as a literal source path, synced under <dest>/{ADHOC_GROUP}/ (basename preserved)."
    )


def _looks_like_path(token: str) -> bool:
    return "/" in token or token.startswith("~") or token.startswith(".")


def _select_sources(
    tokens: tuple, all_groups: bool, include_creds: bool
) -> Tuple[List[str], List[str]]:
    """Split positional tokens into (selected group names, ad-hoc source paths)."""
    group_tokens: List[str] = []
    adhoc_paths: List[str] = []
    for tok in tokens:
        if tok in SOURCE_GROUPS:
            group_tokens.append(tok)
        elif _looks_like_path(tok):
            adhoc_paths.append(tok)
        else:
            raise click.ClickException(
                f"Unknown group or path '{tok}'. Known groups: {', '.join(SOURCE_GROUPS)}. "
                "Ad-hoc source paths must contain '/' or start with '~' or '.'."
            )

    if group_tokens and all_groups:
        raise click.ClickException("Specify GROUPS or --all, not both.")

    if all_groups:
        selected = [name for name in SOURCE_GROUPS if name != "creds"]
    elif group_tokens or adhoc_paths:
        selected = list(dict.fromkeys(group_tokens))
    else:
        selected = list(DEFAULT_GROUPS)

    if "creds" in selected and not include_creds:
        raise click.ClickException(
            "The 'creds' group requires --include-creds (see the security warning)."
        )
    if include_creds and "creds" not in selected:
        selected.append("creds")

    if include_creds:
        click.secho(
            "WARNING: --include-creds will copy SSH/AWS/kube credentials to the "
            "backup host as-is. Prefer rotating and removing them instead of "
            "backing them up unchanged.",
            fg="red", bold=True,
        )

    return selected, adhoc_paths


def _resolve_target(host_override: Optional[str]):
    """Return (ssh_target, extra_ssh_opts).

    Resolves the default EC2 target through the authed API (the Mac cannot reach
    the DB directly). Only the ssh target/host is returned -- the private
    api_token is never sent over the API, and this command uses the Mac's own
    SSH key/agent to connect.
    """
    if host_override:
        return host_override, []

    configs = api_request("GET", "/api/vm-config/list").json()
    vm_name = next(
        (c.get("vm_name") for c in configs if c.get("name") == "default"), None
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
    # Preserve a leading '~/' unquoted so the remote shell expands it; quoting the
    # whole path (shlex.quote) would make mkdir create a literal '~' directory,
    # while rsync expands '~' normally -- so the parent rsync needs never exists.
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
    flags = ["-a", "--compress", "--partial", "--human-readable", "--info=progress2", "--stats"]
    if dry_run:
        flags.append("--dry-run")
    if mirror:
        flags.append("--delete")
    if checksum:
        flags.append("--checksum")
    return flags


def _run_group(name, roots, excludes, target, ssh_opts, dest_root, dry_run, mirror, checksum) -> int:
    remote_group_dir = f"{dest_root.rstrip('/')}/{name}"
    if not dry_run:
        _ensure_remote_dir(target, ssh_opts, remote_group_dir)

    ssh_command = " ".join(["ssh", *ssh_opts]) if ssh_opts else "ssh"
    rc = 0
    for root in roots:
        src_path = Path(root).expanduser()
        if not src_path.exists():
            click.echo(f"  (skip) {root} does not exist locally")
            continue

        filter_args = []
        for pattern in excludes:
            filter_args += ["--exclude", pattern]

        # No trailing slash on the source: rsync recreates the source's own
        # basename under the destination, so <dest>/<name>/<basename>/ is preserved.
        cmd = [
            "rsync", *_rsync_flags(dry_run, mirror, checksum),
            "-e", ssh_command,
            *filter_args,
            str(src_path), f"{target}:{remote_group_dir}/",
        ]

        click.echo(f"\n↑ {name}: {root} -> {target}:{remote_group_dir}/")
        click.echo("  $ " + " ".join(shlex.quote(c) for c in cmd))
        result = subprocess.run(cmd)
        rc = rc or result.returncode

    return rc


@click.command("upload")
@click.argument("groups", nargs=-1)
@click.option("--all", "all_groups", is_flag=True, help="Select all groups except creds")
@click.option("--include-creds", is_flag=True, help="Include the creds group (prints a security warning)")
@click.option("--host", default=None, help="Override EC2 target (user@host or SSH alias); default: VmConfig 'default'")
@click.option("--dest", default=DEFAULT_DEST_ROOT, show_default=True, help="Override the remote destination root")
@click.option("-n", "--dry-run", is_flag=True, help="Show what would transfer, transfer nothing")
@click.option("--mirror", is_flag=True, help="Pass rsync --delete (true mirror; off by default)")
@click.option("--checksum", is_flag=True, help="Content-verify pass (slower)")
@click.option("--list-groups", is_flag=True, help="Print the group -> source mapping and exit")
def upload(groups, all_groups, include_creds, host, dest, dry_run, mirror, checksum, list_groups):
    """Push files from this Mac to the EC2 backup host via rsync over SSH.

    Runs client-side on this Mac and reuses your existing SSH setup (ssh-agent /
    ~/.ssh/config) -- no new secrets are written. GROUPS: zero or more known group
    names (code docs desktop downloads creds) and/or ad-hoc source paths (any token
    containing '/' or starting with '~' or '.', synced under <dest>/misc/). With no
    arguments, syncs the default set (code docs). --dry-run/-n is recommended for
    the first run: it prints the exact rsync command and the would-be file list, and
    transfers nothing.

    Destination defaults to ~/luohy15/backup/mac on the EC2 host resolved via the
    API from the 'default' VmConfig; override with --dest.
    """
    if list_groups:
        _print_group_table()
        return

    selected, adhoc_paths = _select_sources(groups, all_groups, include_creds)

    target, ssh_opts = _resolve_target(host)
    _preflight(target, ssh_opts)

    summary = list(selected) + [f"{ADHOC_GROUP}:{p}" for p in adhoc_paths]
    click.echo(f"Target: {target}   Dest root: {dest}")
    click.echo(f"Sources: {', '.join(summary) or '(none)'}" + ("  (dry-run)" if dry_run else ""))

    failures = []
    for name in selected:
        group = SOURCE_GROUPS[name]
        rc = _run_group(name, group.roots, group.excludes, target, ssh_opts, dest, dry_run, mirror, checksum)
        if rc != 0:
            failures.append(name)

    if adhoc_paths:
        rc = _run_group(ADHOC_GROUP, adhoc_paths, [], target, ssh_opts, dest, dry_run, mirror, checksum)
        if rc != 0:
            failures.append(ADHOC_GROUP)

    click.echo("\n" + "=" * 60)
    status = "DRY-RUN complete (nothing transferred)" if dry_run else "done"
    click.echo(f"Upload {status}. Sources: {', '.join(summary) or '(none)'}")

    if failures:
        raise click.ClickException(f"rsync failed for: {', '.join(failures)}")
