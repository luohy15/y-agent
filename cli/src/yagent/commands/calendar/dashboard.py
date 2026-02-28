"""Generate calendar.md dashboard at $Y_AGENT_HOME/calendar.md."""

import os
from datetime import datetime, timedelta

from yagent.api_client import api_request
from yagent.time_util import utc_to_local


def _agent_home() -> str:
    return os.path.expanduser(os.getenv("Y_AGENT_HOME", "~/.y-agent"))


def update_dashboard() -> str:
    """Regenerate calendar.md dashboard. Returns the file path."""
    home = _agent_home()

    # Today's events
    today = datetime.now().strftime("%Y-%m-%d")
    resp = api_request("GET", "/api/calendar/list", params={"date": today, "limit": 100})
    today_events = resp.json()

    # Upcoming 7 days
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%dT00:00")
    week_end = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%dT23:59")
    resp = api_request("GET", "/api/calendar/list", params={"start": tomorrow, "end": week_end, "limit": 100})
    upcoming = resp.json()

    # Build markdown
    lines = ["# Calendar Dashboard", ""]

    # Today
    lines.append(f"## Today ({today})")
    if today_events:
        lines.append("")
        lines.append("| Time | Summary | Status |")
        lines.append("|------|---------|--------|")
        for e in today_events:
            time_str = utc_to_local(e["start_time"]) if not e.get("all_day") else "All Day"
            lines.append(f"| {time_str} | {e['summary']} | {e.get('status', '')} |")
    else:
        lines.append("")
        lines.append("_No events today._")
    lines.append("")

    # Upcoming
    lines.append("## Upcoming (next 7 days)")
    if upcoming:
        lines.append("")
        lines.append("| Date | Time | Summary |")
        lines.append("|------|------|---------|")
        for e in upcoming:
            local = utc_to_local(e["start_time"])
            lines.append(f"| {local} | {local} | {e['summary']} |")
    else:
        lines.append("")
        lines.append("_No upcoming events._")
    lines.append("")

    path = os.path.join(home, "calendar.md")
    with open(path, "w") as f:
        f.write("\n".join(lines))
    return path
