import os
import xml.etree.ElementTree as ET

import click
import httpx

from yagent.api_client import api_request


def _load_opml(source: str) -> str:
    if source.startswith("http://") or source.startswith("https://"):
        resp = httpx.get(source, timeout=30, follow_redirects=True)
        resp.raise_for_status()
        return resp.text
    with open(os.path.expanduser(source), "r", encoding="utf-8") as f:
        return f.read()


def _extract_feeds(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    feeds = []
    for outline in root.iter("outline"):
        xml_url = outline.attrib.get("xmlUrl")
        if not xml_url:
            continue
        title = outline.attrib.get("title") or outline.attrib.get("text")
        feeds.append({"url": xml_url, "title": title})
    return feeds


@click.command("import-opml")
@click.argument("source")
def rss_import_opml(source):
    """Import RSS feeds from an OPML file or URL."""
    xml_text = _load_opml(source)
    feeds = _extract_feeds(xml_text)
    if not feeds:
        click.echo("No <outline xmlUrl=...> entries found.")
        return

    click.echo(f"Found {len(feeds)} feeds. Importing...")
    created = 0
    failed = 0
    for idx, feed in enumerate(feeds, 1):
        payload = {"url": feed["url"]}
        if feed["title"]:
            payload["title"] = feed["title"]
        try:
            api_request("POST", "/api/rss-feed", json=payload)
            created += 1
        except Exception as exc:
            failed += 1
            click.echo(f"  [{idx}/{len(feeds)}] FAIL {feed['url']}: {exc}", err=True)
        else:
            label = feed["title"] or feed["url"]
            click.echo(f"  [{idx}/{len(feeds)}] OK  {label}")

    click.echo(f"Imported: {created} ok, {failed} failed (server dedupes existing feeds).")
