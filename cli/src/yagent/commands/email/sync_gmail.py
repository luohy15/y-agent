import imaplib
import email
import re
from email.header import decode_header
from email.utils import parsedate_to_datetime
import os
import click
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.expanduser("~"), ".env"))
from yagent.api_client import api_request


def _decode_header_value(value):
    """Decode an RFC 2047 encoded header value."""
    if value is None:
        return None
    parts = decode_header(value)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or 'utf-8', errors='replace'))
        else:
            decoded.append(part)
    return ''.join(decoded)


def _parse_addr_list(value):
    """Parse a comma-separated address header into a list of strings."""
    if not value:
        return []
    decoded = _decode_header_value(value)
    if not decoded:
        return []
    return [addr.strip() for addr in decoded.split(',') if addr.strip()]


def _get_text_body(msg):
    """Extract plain text body from an email message."""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == 'text/plain':
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or 'utf-8'
                    return payload.decode(charset, errors='replace')
        # Fallback: try text/html
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == 'text/html':
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or 'utf-8'
                    return payload.decode(charset, errors='replace')
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or 'utf-8'
            return payload.decode(charset, errors='replace')
    return None


def _parse_email(raw_bytes, thread_id=None):
    """Parse raw email bytes into a dict suitable for the API."""
    msg = email.message_from_bytes(raw_bytes)

    message_id = msg.get('Message-ID', '').strip()
    if not message_id:
        return None

    # Parse date to unix ms
    date_str = msg.get('Date')
    date_ms = 0
    if date_str:
        try:
            dt = parsedate_to_datetime(date_str)
            date_ms = int(dt.timestamp() * 1000)
        except Exception:
            pass

    result = {
        'external_id': message_id,
        'subject': _decode_header_value(msg.get('Subject')),
        'from_addr': _decode_header_value(msg.get('From')) or '',
        'to_addrs': _parse_addr_list(msg.get('To')),
        'cc_addrs': _parse_addr_list(msg.get('Cc')) or None,
        'bcc_addrs': _parse_addr_list(msg.get('Bcc')) or None,
        'date': date_ms,
        'content': _get_text_body(msg),
    }
    if thread_id is not None:
        result['thread_id'] = thread_id
    return result


def _extract_thread_id(fetch_response):
    """Extract X-GM-THRID value from IMAP fetch response data."""
    # fetch_response is like: b'1 (X-GM-THRID 1234567890 RFC822 {size})'
    if not fetch_response:
        return None
    header = fetch_response
    if isinstance(header, bytes):
        header = header.decode('utf-8', errors='replace')
    m = re.search(r'X-GM-THRID\s+(\d+)', header)
    if m:
        return m.group(1)
    return None


@click.command('sync-gmail')
@click.option('--limit', '-l', default=100, type=int,
              help='Max starred emails to fetch (default: 100)')
@click.option('--batch-size', '-b', default=50, type=int,
              help='Batch size for API uploads (default: 50)')
def email_sync_gmail(limit, batch_size):
    """Sync starred emails and their full threads from Gmail via IMAP."""
    email_addr = os.environ.get('GMAIL_ADDRESS')
    password = os.environ.get('GMAIL_APP_PASSWORD')
    if not email_addr or not password:
        raise click.ClickException("GMAIL_ADDRESS and GMAIL_APP_PASSWORD must be set in environment or ~/.env")
    click.echo(f"Connecting to Gmail IMAP as {email_addr}...")

    imap = imaplib.IMAP4_SSL('imap.gmail.com', 993)
    try:
        imap.login(email_addr, password)

        # Step 1: Fetch starred emails with thread IDs
        imap.select('[Gmail]/Starred', readonly=True)
        _, data = imap.search(None, 'ALL')
        msg_nums = data[0].split()
        if not msg_nums:
            click.echo("No starred emails found.")
            return

        msg_nums = msg_nums[-limit:]
        click.echo(f"Found {len(msg_nums)} starred emails. Fetching thread IDs...")

        # Collect unique thread IDs from starred emails
        thread_ids = set()
        for num in msg_nums:
            _, msg_data = imap.fetch(num, '(X-GM-THRID)')
            if msg_data[0] is None:
                continue
            tid = _extract_thread_id(msg_data[0][0] if isinstance(msg_data[0], tuple) else msg_data[0])
            if tid:
                thread_ids.add(tid)

        click.echo(f"Found {len(thread_ids)} unique threads. Fetching full threads from All Mail...")

        # Step 2: Switch to All Mail and fetch all messages in each thread
        imap.select('"[Gmail]/All Mail"', readonly=True)
        emails = []
        seen_ids = set()

        for tid in thread_ids:
            _, data = imap.search(None, f'X-GM-THRID {tid}')
            if not data[0]:
                continue
            thread_nums = data[0].split()
            for num in thread_nums:
                _, msg_data = imap.fetch(num, '(RFC822)')
                if msg_data[0] is None:
                    continue
                raw = msg_data[0][1]
                parsed = _parse_email(raw, thread_id=tid)
                if parsed and parsed['external_id'] not in seen_ids:
                    seen_ids.add(parsed['external_id'])
                    emails.append(parsed)
    finally:
        try:
            imap.close()
        except Exception:
            pass
        imap.logout()

    if not emails:
        click.echo("No emails parsed successfully.")
        return

    click.echo(f"Parsed {len(emails)} emails across {len(thread_ids)} threads. Uploading...")

    total = 0
    for i in range(0, len(emails), batch_size):
        batch = emails[i:i + batch_size]
        resp = api_request("POST", "/api/email/batch", json={"emails": batch})
        total += resp.json().get("count", 0)

    click.echo(f"Synced {total} new emails.")
