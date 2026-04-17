#!/usr/bin/env bash
# SessionStart hook: tag the Warp tab title with `claude:<session_id>` so the
# dashboard's focus-tab logic can match unambiguously when multiple live
# sessions share a cwd (Warp's default tab title is the cwd basename, so
# sibling sessions are otherwise indistinguishable).
#
# Claude Code captures hook stdout, but the hook *process* still has the
# controlling TTY — writing OSC bytes to /dev/tty reaches the terminal
# emulator regardless of what Claude does with stdout.
set -euo pipefail

payload=$(cat)
sid=$(printf '%s' "$payload" | /usr/bin/python3 -c 'import sys,json; print(json.load(sys.stdin).get("session_id",""))' 2>/dev/null || echo "")
[ -z "$sid" ] && exit 0

# OSC 2: set window title. Warp uses it as the tab title. BEL terminator (\a)
# is the widely-supported form; ST (\e\\) also works but BEL is safer in shells.
printf '\033]2;claude:%s\a' "$sid" > /dev/tty 2>/dev/null || true
