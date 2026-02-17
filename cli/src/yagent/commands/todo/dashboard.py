"""Generate todo.md dashboard at $Y_AGENT_HOME/todo.md."""

import os
from datetime import datetime, timedelta
from typing import List
from storage.entity.dto import Todo


def _agent_home() -> str:
    return os.path.expanduser(os.getenv("Y_AGENT_HOME", "~/.y-agent"))


def update_dashboard(user_id: int):
    """Regenerate todo.md dashboard. Called after each todo operation."""
    home = _agent_home()

    from storage.service import todo as todo_service

    # Fetch all non-deleted todos
    all_todos = todo_service.list_todos(user_id, limit=500)

    # Active task (current)
    active = [t for t in all_todos if t.status == "active"]

    # Urgent: due within 2 weeks
    today = datetime.now().date()
    two_weeks = today + timedelta(days=14)
    urgent = []
    for t in all_todos:
        if t.due_date and t.status in ("pending", "active"):
            try:
                due = datetime.strptime(t.due_date, "%Y-%m-%d").date()
                if due <= two_weeks:
                    urgent.append(t)
            except ValueError:
                pass
    urgent.sort(key=lambda t: t.due_date)

    # Important: high priority, not completed/deleted
    important = [t for t in all_todos if t.priority == "high" and t.status in ("pending", "active")]

    # Recent operations: collect from history across all todos (including completed)
    all_with_completed = todo_service.list_todos(user_id, limit=500)
    completed = todo_service.list_todos(user_id, status="completed", limit=100)
    all_with_completed.extend(completed)
    seen_ids = set()
    deduped = []
    for t in all_with_completed:
        if t.todo_id not in seen_ids:
            seen_ids.add(t.todo_id)
            deduped.append(t)

    recent_ops = []
    for t in deduped:
        if t.history:
            for h in t.history:
                recent_ops.append((h.timestamp, h.action, t.name, t.todo_id, h.note))
    recent_ops.sort(key=lambda x: x[0], reverse=True)
    recent_ops = recent_ops[:10]

    # Build markdown
    lines = ["# Todo Dashboard", ""]

    # Current task
    lines.append("## Current Task")
    if active:
        for t in active:
            lines.append("")
            _append_todo_detail(lines, t)
    else:
        lines.append("")
        lines.append("_No active task._")
    lines.append("")

    # Urgent tasks
    lines.append("## Urgent (due within 2 weeks)")
    if urgent:
        lines.append("")
        lines.append("| Name | Due | Priority | ID |")
        lines.append("|------|-----|----------|----|")
        for t in urgent:
            lines.append(f"| {t.name} | {t.due_date} | {t.priority or '-'} | {t.todo_id} |")
    else:
        lines.append("")
        lines.append("_No urgent tasks._")
    lines.append("")

    # Important tasks
    lines.append("## Important (high priority)")
    if important:
        lines.append("")
        lines.append("| Name | Status | Due | ID |")
        lines.append("|------|--------|-----|----|")
        for t in important:
            lines.append(f"| {t.name} | {t.status} | {t.due_date or '-'} | {t.todo_id} |")
    else:
        lines.append("")
        lines.append("_No high-priority tasks._")
    lines.append("")

    # Recent operations
    lines.append("## Recent Operations")
    if recent_ops:
        lines.append("")
        lines.append("| Time | Action | Task | Note |")
        lines.append("|------|--------|------|------|")
        for ts, action, name, tid, note in recent_ops:
            note_str = note or ""
            lines.append(f"| {ts} | {action} | {name} | {note_str} |")
    else:
        lines.append("")
        lines.append("_No recent operations._")
    lines.append("")

    path = os.path.join(home, "todo.md")
    with open(path, "w") as f:
        f.write("\n".join(lines))


def _append_todo_detail(lines: List[str], t: Todo):
    lines.append(f"**{t.name}** (`{t.todo_id}`)")
    if t.desc:
        lines.append(f"- Description: {t.desc}")
    if t.priority:
        lines.append(f"- Priority: {t.priority}")
    if t.due_date:
        lines.append(f"- Due: {t.due_date}")
    if t.tags:
        lines.append(f"- Tags: {', '.join(t.tags)}")
    if t.progress:
        lines.append(f"- Progress: {t.progress}")
