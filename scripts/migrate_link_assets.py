#!/usr/bin/env python3
"""Migrate legacy link assets into EC2 ~/luohy15/links/<link_id>/ storage."""

from __future__ import annotations

import argparse
import io
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import paramiko
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "storage" / "src"))
sys.path.insert(0, str(ROOT / "agent" / "src"))

from agent.tools.ssh_exec import _parse_ssh_target  # noqa: E402
from storage.entity.link import LinkActivityEntity, LinkEntity  # noqa: E402
from storage.entity.vm_config import VmConfigEntity  # noqa: E402
from storage.global_config import load_global_config  # noqa: E402

HOME = Path.home() / "luohy15"
WEB_ROOT = HOME / "assets" / "web"
TLDR_ROOT = HOME / "assets" / "tldr"
REPORT = ROOT / "scripts" / "migration-report-2216.md"
ORPHANS = ROOT / "scripts" / "migration-report-2216-orphans.md"


@dataclass
class Match:
    link: LinkEntity
    activity: LinkActivityEntity | None


@dataclass
class TargetVm:
    user: str | None
    host: str
    port: int
    api_token: str


def load_database_url() -> str:
    load_global_config()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL not found in env or ~/.y-agent/config.toml")
    return database_url


def candidate_urls(path: Path, root: Path) -> list[str]:
    rel = path.relative_to(root)
    parts = rel.parts
    if len(parts) < 4 or parts[1] not in {"http", "https"}:
        return []
    scheme = parts[1]
    host = parts[2].replace("_", ":")
    tail = "/".join(parts[3:]).removesuffix(".md")
    if tail == "index":
        base = f"{scheme}://{host}/"
    else:
        base = f"{scheme}://{host}/{quote(tail, safe='/%:@?=&+-._~')}"
    candidates = [base]
    if not base.endswith("/") and not base.endswith(".html"):
        candidates.append(base + ".html")
    return candidates


def find_match(session, urls: list[str]) -> Match | None:
    for url in urls:
        fragless = url.split("#", 1)[0]
        base_url = fragless.split("?", 1)[0]
        link = session.query(LinkEntity).filter_by(base_url=base_url).first()
        if not link:
            continue
        activity = None
        if fragless != base_url:
            activity = session.query(LinkActivityEntity).filter_by(link_id=link.id, url=fragless).first()
        return Match(link=link, activity=activity)
    return None


def destination(match: Match, kind: str) -> tuple[str, str, bool]:
    filename = "summary.md" if kind == "tldr" else "content.md"
    if match.activity:
        key = f"links/{match.link.link_id}/{match.activity.activity_id}/{filename}"
        return f"luohy15/{key}", key, True
    key = f"links/{match.link.link_id}/{filename}"
    return f"luohy15/{key}", key, False


def load_target_vm(session, name: str) -> TargetVm:
    row = session.query(VmConfigEntity).filter_by(name=name).order_by(VmConfigEntity.user_id.asc()).first()
    if not row or not row.vm_name or not row.api_token:
        raise SystemExit(f"vm_config {name!r} with vm_name/api_token not found")
    user, host, port = _parse_ssh_target(row.vm_name)
    return TargetVm(user=user, host=host, port=port, api_token=row.api_token)


def connect(vm: TargetVm) -> paramiko.SSHClient:
    key = paramiko.Ed25519Key.from_private_key(io.StringIO(vm.api_token))
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(vm.host, port=vm.port, username=vm.user, pkey=key, timeout=20)
    return client


def remote_exists(client: paramiko.SSHClient, remote_path: str) -> bool:
    command = f"test -f ~/{remote_path}"
    _, stdout, _ = client.exec_command(command)
    return stdout.channel.recv_exit_status() == 0


def upload(client: paramiko.SSHClient, local_path: Path, remote_path: str) -> None:
    mkdir_cmd = f"mkdir -p ~/$(dirname {sh_quote(remote_path)})"
    _, stdout, stderr = client.exec_command(mkdir_cmd)
    status = stdout.channel.recv_exit_status()
    if status != 0:
        raise RuntimeError(stderr.read().decode("utf-8", "replace"))
    with client.open_sftp() as sftp:
        sftp.put(str(local_path), f"./{remote_path}")


def sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def migrate_kind(session, client, root: Path, kind: str, dry_run: bool) -> tuple[int, int, list[str]]:
    migrated = 0
    orphan = 0
    orphan_lines: list[str] = []
    if not root.exists():
        return 0, 0, []
    for path in sorted(root.rglob("*.md")):
        urls = candidate_urls(path, root)
        match = find_match(session, urls)
        if not match:
            orphan += 1
            orphan_lines.append(f"- {kind}: {path} -> {', '.join(urls) or 'unrecognized'}")
            continue
        remote_path, key, is_activity = destination(match, kind)
        current_key = (match.activity.summary_content_key if is_activity else match.link.summary_content_key) if kind == "tldr" else (match.activity.content_key if is_activity else match.link.content_key)
        if current_key == key and (dry_run or remote_exists(client, remote_path)):
            continue
        migrated += 1
        if dry_run:
            continue
        upload(client, path, remote_path)
        if kind == "tldr":
            if is_activity:
                match.activity.summary_content_key = key
            else:
                match.link.summary_content_key = key
        else:
            if is_activity:
                match.activity.content_key = key
                match.activity.download_status = "done"
            else:
                match.link.content_key = key
                match.link.download_status = "done"
    return migrated, orphan, orphan_lines


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--vm", default="default", help="vm_config name to target (default: default)")
    args = parser.parse_args()

    engine = create_engine(load_database_url())
    Session = sessionmaker(bind=engine)
    with Session() as session:
        vm = load_target_vm(session, args.vm)
        client = connect(vm)
        try:
            web_migrated, web_orphan, web_orphans = migrate_kind(session, client, WEB_ROOT, "web", args.dry_run)
            tldr_migrated, tldr_orphan, tldr_orphans = migrate_kind(session, client, TLDR_ROOT, "tldr", args.dry_run)
            if not args.dry_run:
                session.commit()
        finally:
            client.close()

    total_migrated = web_migrated + tldr_migrated
    total_orphan = web_orphan + tldr_orphan
    action = "would-migrate" if args.dry_run else "migrated"
    print(f"{action}={total_migrated} orphan={total_orphan} web={web_migrated} tldr={tldr_migrated}")
    REPORT.write_text(
        "# migration-report-2216\n\n"
        f"- dry_run: {args.dry_run}\n"
        f"- {action}: {total_migrated}\n"
        f"- orphan: {total_orphan}\n"
        f"- web: {web_migrated}\n"
        f"- tldr: {tldr_migrated}\n",
        encoding="utf-8",
    )
    ORPHANS.write_text("# migration-report-2216-orphans\n\n" + "\n".join(web_orphans + tldr_orphans) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
