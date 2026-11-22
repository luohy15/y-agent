"""Homepage admission: maintainer, approved row, otherwise refuse.

The user table is not an allowlist. Rollout inserts only the resolved
maintainer email and the named account.
"""

import os

from loguru import logger

from storage.repository import user as user_repo
from storage.repository import user_access as access_repo
from storage.util import get_telegram_bot_token, send_telegram_message_checked

ROLLOUT_EMAIL = "roy.luo@alphavantage.co"
_MAINTAINER_ENV = "Y_AGENT_MODULE_MAINTAINER_USER_ID"


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def resolve_maintainer() -> dict:
    """Return internal id, normalized email, and public id.

    The configured value may be a public user id or an email. Unset,
    unknown, or an account with no email means there is no maintainer.
    """
    configured = os.environ.get(_MAINTAINER_ENV, "").strip()
    empty = {"internal_id": None, "email": None, "public_id": None}
    if not configured:
        return empty
    try:
        if "@" in configured:
            email = normalize_email(configured)
            user = user_repo.get_user_by_normalized_email(email)
            return {
                "internal_id": user.id if user else None,
                "email": email,
                "public_id": user.user_id if user else None,
            }
        user = user_repo.get_user_by_user_id(configured)
    except Exception:
        logger.exception("maintainer resolution failed")
        return empty
    if not user or not user.email:
        return empty
    return {
        "internal_id": user.id,
        "email": normalize_email(user.email),
        "public_id": user.user_id,
    }


def _maintainer_email() -> str | None:
    try:
        return resolve_maintainer()["email"]
    except Exception:
        logger.exception("maintainer email lookup failed")
        return None


def admission_state(email: str) -> str:
    """approved, pending, or required. Lookup errors refuse."""
    normalized = normalize_email(email)
    try:
        maintainer_email = _maintainer_email()
        if maintainer_email and normalized == maintainer_email:
            return "approved"
        row = access_repo.get_by_email(normalized)
    except Exception:
        logger.exception("admission lookup failed email={}", normalized)
        return "required"
    if row and row["status"] == "approved":
        return "approved"
    if row and row["status"] == "pending":
        return "pending"
    return "required"


def _as_internal_id(value) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def request_admitted(internal_user_id, token_email: str | None) -> dict:
    """Middleware check. Maintainer by internal id, then one email lookup."""
    try:
        user_id = _as_internal_id(internal_user_id)
        maintainer = resolve_maintainer()
        if user_id is not None and maintainer["internal_id"] == user_id:
            return {"admitted": True, "state": None}
        email = normalize_email(token_email or "")
        if not email and user_id is not None:
            user = user_repo.get_user_by_id(user_id)
            email = normalize_email(user.email) if user and user.email else ""
        if not email:
            return {"admitted": False, "state": "required"}
        if maintainer["email"] and email == maintainer["email"]:
            return {"admitted": True, "state": None}
        row = access_repo.get_by_email(email)
    except Exception:
        logger.exception("admission check failed")
        return {"admitted": False, "state": "required"}
    if row and row["status"] == "approved":
        return {"admitted": True, "state": None}
    if row and row["status"] == "pending":
        return {"admitted": False, "state": "pending"}
    return {"admitted": False, "state": "required"}


def record_request(email: str) -> dict:
    """Create or refresh a waitlist row. Approved identities are not mutated."""
    normalized = normalize_email(email)
    state = admission_state(normalized)
    if state == "approved":
        return {"status": "approved", "created": False}
    if state == "pending":
        access_repo.bump_request(normalized)
        return {"status": "pending", "created": False}
    created = access_repo.insert_pending(normalized)
    if not created:
        state = admission_state(normalized)
        if state == "approved":
            return {"status": "approved", "created": False}
        access_repo.bump_request(normalized)
        return {"status": "pending", "created": False}
    try:
        deliver_notice(normalized)
    except Exception:
        logger.exception("access notice failed email={}", normalized)
    return {"status": "pending", "created": True}


def _notice_text(email: str, requested_at: str | None) -> str:
    return (
        f"Access request: {email}\n"
        f"Requested: {requested_at or ''}\n"
        f"y access approve {email}"
    )


def _notice_failure(row: dict) -> str | None:
    token = get_telegram_bot_token()
    if not token:
        return "telegram bot token unset"
    maintainer = resolve_maintainer()
    if maintainer["internal_id"] is None:
        return "maintainer unresolved"
    user = user_repo.get_user_by_id(maintainer["internal_id"])
    if not user or not user.telegram_id:
        return "maintainer telegram unbound"
    text = _notice_text(row["email"], row.get("first_requested_at"))
    if not send_telegram_message_checked(token, user.telegram_id, text):
        return "telegram send failed"
    return None


def deliver_notice(email: str) -> str:
    claimed = access_repo.claim_notice(normalize_email(email))
    if not claimed:
        return "not_claimed"
    try:
        error = _notice_failure(claimed)
    except Exception:
        logger.exception("access notice send failed email={}", claimed["email"])
        error = "telegram send failed"
    if error is None:
        access_repo.mark_notice_sent(claimed["email"])
        return "sent"
    status = access_repo.mark_notice_attempt_failed(claimed["email"], error)
    return status or "pending"


def retry_notifications() -> dict:
    seen = sent = failed = pending = 0
    try:
        emails = access_repo.list_due_notice_emails()
    except Exception:
        logger.exception("access notice retry list failed")
        return {
            "status": "error",
            "action": "retry_access_notifications",
            "seen": 0,
            "sent": 0,
            "failed": 0,
            "pending": 0,
        }
    for email in emails:
        seen += 1
        try:
            outcome = deliver_notice(email)
        except Exception:
            logger.exception("access notice retry failed email={}", email)
            pending += 1
            continue
        if outcome == "sent":
            sent += 1
        elif outcome == "failed":
            failed += 1
        elif outcome == "pending":
            pending += 1
    return {
        "status": "ok",
        "action": "retry_access_notifications",
        "seen": seen,
        "sent": sent,
        "failed": failed,
        "pending": pending,
    }


def approve(email: str, decided_by: str) -> dict | None:
    normalized = normalize_email(email)
    result = access_repo.approve(normalized, decided_by)
    if result is None:
        return None
    row, changed = result
    if changed:
        logger.info("access approved email={} decided_by={}", normalized, decided_by)
    return row


def list_applications(status: str | None = None) -> list[dict]:
    return access_repo.list_applications(status)


def inventory() -> list[dict]:
    """Read-only user inventory. Does not write an admission row."""
    maintainer = resolve_maintainer()
    rows = {row["email"]: row for row in access_repo.list_all()}
    items = []
    for user in user_repo.list_users():
        email = normalize_email(user.email) if user.email else ""
        access = rows.get(email) if email else None
        is_maintainer = maintainer["internal_id"] is not None and user.id == maintainer["internal_id"]
        if is_maintainer:
            admission_status = "approved"
        elif access:
            admission_status = access["status"]
        else:
            admission_status = None
        items.append({
            "user_id": user.user_id,
            "email": user.email,
            "created_at": user.created_at,
            "maintainer": is_maintainer,
            "admission_status": admission_status,
        })
    return items


def seed_rollout() -> dict:
    """Idempotent seed of the maintainer email and the named account only."""
    emails = []
    maintainer_email = _maintainer_email()
    if maintainer_email:
        emails.append(maintainer_email)
    else:
        logger.warning("seed_access_rollout: maintainer email unresolved")
    if ROLLOUT_EMAIL not in emails:
        emails.append(ROLLOUT_EMAIL)
    results = {}
    for email in emails:
        results[email] = access_repo.ensure_rollout(email)
    return {"status": "ok", "action": "seed_access_rollout", "results": results}
