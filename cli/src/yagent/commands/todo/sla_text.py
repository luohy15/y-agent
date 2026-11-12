from datetime import date

from storage.util import local_today


def sla_label(todo: dict) -> str:
    if todo.get("pinned"):
        return "long-term"
    due = todo.get("sla_due_at")
    if not due:
        return "-"
    if todo.get("status") not in ("pending", "active", "awaiting"):
        return f"{due} (closed)"
    days = (date.fromisoformat(due) - local_today()).days
    label = f"{abs(days)}d overdue" if days < 0 else f"{days}d remaining"
    return f"{due} ({label})"
