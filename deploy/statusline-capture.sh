#!/usr/bin/env bash
# Statusline command for Claude Code that persists rate_limits to disk
# and displays a short usage summary in the terminal status line.
#
# Usage in settings.json:
#   "statusLine": { "type": "command", "command": "/path/to/statusline-capture.sh ~/.claude" }
#
# Input: Claude Code pipes JSON with rate_limits, context_window, etc. on stdin.
# Output: Short status string shown beneath the Claude Code input area.

CONFIG_DIR="${1:?Usage: statusline-capture.sh <config_dir>}"
INPUT=$(cat)

# Persist rate_limits to disk (atomic write) and emit a status line string.
# Using python3 since it's already a dashboard dependency.
echo "$INPUT" | python3 -c "
import json, sys, os, time

data = json.load(sys.stdin)
rl = data.get('rate_limits')

# Write rate_limits to file if present
if rl:
    rl['updated_at'] = time.time()
    out = os.path.join('${CONFIG_DIR}', 'rate-limits.json')
    tmp = out + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(rl, f)
    os.replace(tmp, out)

# Emit status line: usage percentages
parts = []
if rl:
    fh = rl.get('five_hour')
    sd = rl.get('seven_day')
    if fh:
        parts.append(f\"5h: {fh['used_percentage']:.0f}%\")
    if sd:
        parts.append(f\"7d: {sd['used_percentage']:.0f}%\")

if parts:
    print(' | '.join(parts))
" 2>/dev/null
