"""Pure completion-promise rules shared by todo reads and writes."""

import re
from datetime import date, timedelta

OPEN_STATUSES = ("pending", "active", "awaiting")


def default_days(priority: str | None) -> int:
    return {"high": 3, "low": 14}.get(priority, 7)


def resolve_sla(sla: str | None, priority: str | None, today: date) -> str:
    if sla is None:
        days = default_days(priority)
    elif re.fullmatch(r"[0-9]+[dw]", sla):
        days = int(sla[:-1]) * (7 if sla[-1] == "w" else 1)
    else:
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", sla):
                raise ValueError
            days = (date.fromisoformat(sla) - today).days
        except (ValueError, TypeError) as exc:
            raise ValueError("SLA must be Nd, Nw or YYYY-MM-DD") from exc
    if not 0 <= days <= 14:
        raise ValueError("SLA must be today through today+14 days; use --pin for a long-term goal")
    return (today + timedelta(days=days)).isoformat()


def is_overdue(sla_due_at: str | None, pinned: bool, status: str, today: date) -> bool:
    return bool(status in OPEN_STATUSES and not pinned and sla_due_at and sla_due_at < today.isoformat())


def bucket_for(sla_due_at: str | None, pinned: bool, status: str, today: date) -> str | None:
    if status not in OPEN_STATUSES:
        return None
    if pinned:
        return "longterm"
    if not sla_due_at:
        return None
    due = date.fromisoformat(sla_due_at)
    if due < today:
        return "overdue"
    if due == today:
        return "today"
    if due <= today + timedelta(days=6 - today.weekday()):
        return "week"
    if (due.year, due.month) == (today.year, today.month):
        return "month"
    return "later"


def format_digest(audit: dict) -> str | None:
    if not audit["overdue"] and not audit["due_today"]:
        return None
    lines = ["Todo SLA"]
    for key, title in (("overdue", "Overdue: renew or archive"), ("due_today", "Due today")):
        if audit[key]:
            lines.append(f"\n{title} ({len(audit[key])})")
            lines.extend(f"{t['todo_id']} {t['name']} ({t['sla_due_at']})" for t in audit[key])
    return "\n".join(lines)
