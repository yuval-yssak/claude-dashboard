"""Static configuration: env vars, paths, and tuning constants.

Owns: PORT, CONFIG_DIRS, ANNOTATIONS_FILE, TODO_SCAN_LINES, DEBOUNCE_SECONDS, PERIODIC_INTERVAL.
Depends on: stdlib only.
"""

import os

PORT = int(os.environ.get("CLAUDE_DASHBOARD_PORT", 8484))

DEFAULT_CONFIGS = os.environ.get(
    "CLAUDE_CONFIGS",
    "~/.claude,~/.claude-personal",
)

CONFIG_DIRS = [
    os.path.expanduser(d.strip()) for d in DEFAULT_CONFIGS.split(",")
]

# How many tail-lines to scan for the latest TodoWrite
TODO_SCAN_LINES = 2000

# Persistent annotations file (in project root, one level up from server/)
ANNOTATIONS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "claude-dashboard-data.json",
)

DEBOUNCE_SECONDS = 0.5
PERIODIC_INTERVAL = 5  # seconds — for PID/activity checks
