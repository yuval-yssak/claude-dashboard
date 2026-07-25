#!/usr/bin/env bash
# Statusline command for Claude Code that persists rate_limits to disk
# and displays model, cwd, git branch, context-remaining, and rate-limit
# usage in the terminal status line.
#
# Usage in settings.json:
#   "statusLine": { "type": "command", "command": "/path/to/statusline-capture.sh ~/.claude" }
#
# Input: Claude Code pipes JSON with model, workspace, context_window,
# rate_limits, etc. on stdin.
# Output: Short status string shown beneath the Claude Code input area.

CONFIG_DIR="${1:?Usage: statusline-capture.sh <config_dir>}"
INPUT=$(cat)

# Directory + git branch are derived here (not in the python block below)
# since `git` is already skipping optional locks for a fast, read-only call.
CURRENT_DIR=$(echo "$INPUT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('workspace',{}).get('current_dir',''))" 2>/dev/null)
DIR_LABEL=$(basename "${CURRENT_DIR:-$PWD}")
GIT_BRANCH=$(git -C "${CURRENT_DIR:-$PWD}" --no-optional-locks branch --show-current 2>/dev/null)

# Persist rate_limits to disk (atomic write) and emit a status line string.
# Using python3 since it's already a dashboard dependency.
echo "$INPUT" | DIR_LABEL="$DIR_LABEL" GIT_BRANCH="$GIT_BRANCH" python3 -c "
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

parts = []

# Model name
model = data.get('model', {}).get('display_name')
if model:
    parts.append(model)

# Current directory (basename) + optional git branch
dir_label = os.environ.get('DIR_LABEL')
git_branch = os.environ.get('GIT_BRANCH')
if dir_label:
    parts.append(f\"{dir_label} ({git_branch})\" if git_branch else dir_label)

# Context window remaining percentage
ctx = data.get('context_window') or {}
remaining = ctx.get('remaining_percentage')
if remaining is not None:
    parts.append(f\"ctx: {remaining:.0f}% left\")

# Claude.ai subscription rate-limit usage
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
