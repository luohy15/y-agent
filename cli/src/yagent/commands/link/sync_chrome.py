import os
import shutil
import sqlite3
import tempfile
import click
from yagent.api_client import api_request


# Chrome timestamps are microseconds since 1601-01-01
CHROME_EPOCH_OFFSET_US = 11644473600 * 1_000_000


def _chrome_to_unix_ms(chrome_us: int) -> int:
    return (chrome_us - CHROME_EPOCH_OFFSET_US) // 1000


def _read_chrome_history(db_path: str, since_ms: int | None = None) -> list[dict]:
    """Read Chrome history from a copied SQLite DB.

    Returns list of dicts: {url, title, timestamp (unix ms)}.
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        query = """
            SELECT u.url, u.title, v.visit_time
            FROM visits v
            JOIN urls u ON v.url = u.id
        """
        params: list = []
        if since_ms is not None:
            chrome_since = since_ms * 1000 + CHROME_EPOCH_OFFSET_US
            query += " WHERE v.visit_time > ?"
            params.append(chrome_since)
        query += " ORDER BY v.visit_time ASC"

        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()

    results = []
    for url, title, visit_time in rows:
        results.append({
            "url": url,
            "title": title or None,
            "timestamp": _chrome_to_unix_ms(visit_time),
        })
    return results


def _get_default_chrome_path() -> str:
    return os.path.expanduser(
        "~/Library/Application Support/Google/Chrome/Default/History"
    )


@click.command('sync-chrome')
@click.option('--db', '-d', 'db_path', default=None,
              help='Path to Chrome History SQLite file (default: Chrome Default profile)')
@click.option('--since', '-s', 'since_days', default=7, type=int,
              help='Sync history from last N days (default: 7)')
@click.option('--batch-size', '-b', default=500, type=int,
              help='Batch size for DB inserts (default: 500)')
def link_sync_chrome(db_path, since_days, batch_size):
    """Sync browser history from Chrome into links."""
    if not db_path:
        db_path = _get_default_chrome_path()

    if not os.path.exists(db_path):
        click.echo(f"Chrome history not found: {db_path}")
        return

    # Copy DB since Chrome locks it
    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tmp.close()
    try:
        shutil.copy2(db_path, tmp.name)

        # Calculate since_ms
        import time
        since_ms = int((time.time() - since_days * 86400) * 1000) if since_days > 0 else None

        entries = _read_chrome_history(tmp.name, since_ms)
    finally:
        os.unlink(tmp.name)

    if not entries:
        click.echo("No new history entries found.")
        return

    click.echo(f"Found {len(entries)} history entries from last {since_days} days.")

    # Batch upload via API
    total = 0
    for i in range(0, len(entries), batch_size):
        batch = entries[i:i + batch_size]
        resp = api_request("POST", "/api/link/batch", json={"links": batch})
        total += resp.json().get("count", 0)

    click.echo(f"Synced {total} links.")
