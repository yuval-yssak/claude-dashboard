"""Pure formatting helpers used across the package.

Owns: nothing.
Depends on: stdlib only.
"""

import os
from datetime import datetime, timezone


def friendly_project_name(dir_name: str) -> str:
    if dir_name.startswith("-sessions-"):
        raw = dir_name[len("-sessions-"):]
    else:
        raw = dir_name
    path = "/" + raw.replace("-", "/")
    # Collapse double slash and replace home dir with ~
    path = path.replace("//", "/")
    home = os.path.expanduser("~")
    if path.startswith(home):
        path = "~" + path[len(home):]
    return path


def abbreviate_home(path: str) -> str:
    """Replace the user's home prefix with ~. Input must be an absolute path."""
    if not path:
        return path
    home = os.path.expanduser("~")
    if path == home:
        return "~"
    if path.startswith(home + "/"):
        return "~" + path[len(home):]
    return path


def time_ago(iso_ts: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - dt
        secs = int(delta.total_seconds())
        if secs < 0:
            return "just now"
        if secs < 60:
            return f"{secs}s ago"
        mins = secs // 60
        if mins < 60:
            return f"{mins}m ago"
        hours = mins // 60
        if hours < 24:
            return f"{hours}h ago"
        days = hours // 24
        return f"{days}d ago"
    except Exception:
        return "unknown"
