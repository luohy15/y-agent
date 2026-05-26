#!/usr/bin/env python3
"""Migrate legacy link assets into local ~/luohy15/links/<link_id>/ storage."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "storage" / "src"))
sys.path.insert(0, str(ROOT / "agent" / "src"))

from storage.entity.link import LinkActivityEntity, LinkEntity  # noqa: E402
from storage.global_config import load_global_config  # noqa: E402
from storage.repository import link as link_repo  # noqa: E402

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
class MigrationStats:
    web_migrated: int = 0
    tldr_migrated: int = 0
    web_created: int = 0
    tldr_attached: int = 0
    unresolvable_tldr: int = 0
    web_orphan: int = 0
    create_lines: list[str] = field(default_factory=list)
    orphan_lines: list[str] = field(default_factory=list)
    unresolvable_lines: list[str] = field(default_factory=list)


def load_database_url() -> str:
    load_dotenv(ROOT / ".env")
    load_global_config()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL not found in env, repo .env, or ~/.y-agent/config.toml")
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


def canonical_url(urls: list[str]) -> str | None:
    return urls[0] if urls else None


def mtime_ms(path: Path) -> int:
    try:
        return int(path.stat().st_mtime * 1000)
    except OSError:
        import time

        return int(time.time() * 1000)


def title_from_url(url: str, path: Path) -> str:
    parsed = urlparse(url)
    tail = unquote(parsed.path.rstrip("/").rsplit("/", 1)[-1])
    if not tail:
        tail = parsed.netloc or path.stem
    title = tail.removesuffix(".html").removesuffix(".md").replace("-", "_").replace("_", " ").strip()
    return title or path.stem


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
        return key, key, True
    key = f"links/{match.link.link_id}/{filename}"
    return key, key, False


def current_content_key(match: Match, kind: str, is_activity: bool) -> str | None:
    if kind == "tldr":
        return match.activity.summary_content_key if is_activity else match.link.summary_content_key
    return match.activity.content_key if is_activity else match.link.content_key


def copy_asset(path: Path, target_rel_path: str) -> None:
    target_path = HOME / target_rel_path
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target_path)


def migrate_existing_kind(session, root: Path, kind: str, dry_run: bool, stats: MigrationStats) -> None:
    if not root.exists():
        return
    for path in sorted(root.rglob("*.md")):
        urls = candidate_urls(path, root)
        match = find_match(session, urls)
        if not match:
            if kind == "tldr":
                stats.unresolvable_tldr += 1
                stats.unresolvable_lines.append(f"- tldr: {path} -> {', '.join(urls) or 'unrecognized'}")
            continue
        target_rel_path, key, is_activity = destination(match, kind)
        target_path = HOME / target_rel_path
        if current_content_key(match, kind, is_activity) == key and (dry_run or target_path.exists()):
            continue
        if kind == "web":
            stats.web_migrated += 1
        else:
            stats.tldr_migrated += 1
        if dry_run:
            continue
        copy_asset(path, target_rel_path)
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


def promote_web_orphans(session, root: Path, dry_run: bool, stats: MigrationStats) -> None:
    if not root.exists():
        return
    for path in sorted(root.rglob("*.md")):
        urls = candidate_urls(path, root)
        if find_match(session, urls):
            continue
        url = canonical_url(urls)
        if not url:
            stats.web_orphan += 1
            stats.orphan_lines.append(f"- web: {path} -> unrecognized")
            continue
        link = link_repo.create_link_entity_for_migration(
            session,
            url,
            title_from_url(url, path),
            mtime_ms(path),
            "__pending__",
        )
        content_key = f"links/{link.link_id}/content.md"
        link.content_key = content_key
        link.download_status = "done"
        link_id = link.link_id
        if not dry_run:
            copy_asset(path, content_key)
        stats.web_created += 1
        stats.create_lines.append(f"- {url} -> link_id={link_id} content_key={content_key} source={path}")


def attach_tldr_orphans(session, root: Path, dry_run: bool, stats: MigrationStats) -> None:
    if not root.exists():
        return
    for path in sorted(root.rglob("*.md")):
        urls = candidate_urls(path, root)
        match = find_match(session, urls)
        if not match:
            stats.unresolvable_tldr += 1
            stats.unresolvable_lines.append(f"- tldr: {path} -> {', '.join(urls) or 'unrecognized'}")
            continue
        target_rel_path, key, is_activity = destination(match, "tldr")
        target_path = HOME / target_rel_path
        if current_content_key(match, "tldr", is_activity) == key and (dry_run or target_path.exists()):
            continue
        stats.tldr_attached += 1
        if dry_run:
            continue
        copy_asset(path, target_rel_path)
        if is_activity:
            match.activity.summary_content_key = key
        else:
            match.link.summary_content_key = key


def write_reports(stats: MigrationStats, dry_run: bool) -> None:
    migrate_action = "would-migrate" if dry_run else "migrated"
    create_action = "would-create-link" if dry_run else "created-link"
    attach_action = "would-attach-tldr" if dry_run else "attached-tldr"
    total_migrated = stats.web_migrated + stats.tldr_migrated
    REPORT.write_text(
        "# migration-report-2216\n\n"
        f"- dry_run: {dry_run}\n"
        f"- {migrate_action}: {total_migrated}\n"
        f"- web: {stats.web_migrated}\n"
        f"- tldr: {stats.tldr_migrated}\n"
        f"- {create_action}: {stats.web_created}\n"
        f"- {attach_action}: {stats.tldr_attached}\n"
        f"- unresolvable-tldr: {stats.unresolvable_tldr}\n"
        f"- orphan: {stats.web_orphan + stats.unresolvable_tldr}\n"
        "\n## Create LinkEntity\n\n"
        + ("\n".join(stats.create_lines) if stats.create_lines else "- none")
        + "\n\n## Unresolvable TLDR\n\n"
        + ("\n".join(stats.unresolvable_lines) if stats.unresolvable_lines else "- none")
        + "\n",
        encoding="utf-8",
    )
    ORPHANS.write_text(
        "# migration-report-2216-orphans\n\n"
        "## Web Orphans Promoted\n\n"
        + ("\n".join(stats.create_lines) if stats.create_lines else "- none")
        + "\n\n## Unresolvable TLDR\n\n"
        + ("\n".join(stats.unresolvable_lines) if stats.unresolvable_lines else "- none")
        + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    engine = create_engine(load_database_url())
    Session = sessionmaker(bind=engine)
    stats = MigrationStats()
    with Session() as session:
        migrate_existing_kind(session, WEB_ROOT, "web", args.dry_run, stats)
        promote_web_orphans(session, WEB_ROOT, args.dry_run, stats)
        attach_tldr_orphans(session, TLDR_ROOT, args.dry_run, stats)
        if args.dry_run:
            session.rollback()
        else:
            session.commit()

    migrate_action = "would-migrate" if args.dry_run else "migrated"
    create_action = "would-create" if args.dry_run else "created"
    attach_action = "would-attach-tldr" if args.dry_run else "attached-tldr"
    total_migrated = stats.web_migrated + stats.tldr_migrated
    print(
        f"{migrate_action}={total_migrated} "
        f"{create_action}={stats.web_created} "
        f"{attach_action}={stats.tldr_attached} "
        f"unresolvable-tldr={stats.unresolvable_tldr} "
        f"orphan={stats.web_orphan + stats.unresolvable_tldr} "
        f"web={stats.web_migrated} tldr={stats.tldr_migrated}"
    )
    write_reports(stats, args.dry_run)


if __name__ == "__main__":
    main()
