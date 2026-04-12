#!/usr/bin/env python3
"""
Claude Sessions Dashboard
=========================
A live-updating dashboard for tracking multiple Claude Code sessions
across two accounts / config directories.  Includes per-session notes
and custom todo lists that persist to disk.

Usage:
    python3 claude-dashboard.py
    # Then open http://localhost:8484 in your browser

Environment variables (optional):
    CLAUDE_DASHBOARD_PORT  - Port to serve on (default: 8484)
    CLAUDE_CONFIGS         - Comma-separated list of config dirs
                             (default: ~/.claude,~/.claude-personal)
"""

import glob
import http.server
import json
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    HAS_WATCHDOG = True
except ImportError:
    HAS_WATCHDOG = False

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

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
ANNOTATIONS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "claude-dashboard-data.json")

# ---------------------------------------------------------------------------
# Annotations store  (notes + custom todos per session, persisted to JSON)
# ---------------------------------------------------------------------------

_annotations_lock = threading.Lock()
_annotations: dict = {}


def _load_annotations():
    global _annotations
    try:
        with open(ANNOTATIONS_FILE) as f:
            _annotations = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        _annotations = {}


def _save_annotations():
    tmp = ANNOTATIONS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(_annotations, f, indent=2)
    os.replace(tmp, ANNOTATIONS_FILE)


def get_annotation(session_id: str) -> dict:
    with _annotations_lock:
        return _annotations.get(session_id, {"notes": "", "todos": []})


def set_annotation(session_id: str, data: dict):
    with _annotations_lock:
        _annotations[session_id] = data
        _save_annotations()


# Load on startup
_load_annotations()

# ---------------------------------------------------------------------------
# Session cache + SSE broadcast
# ---------------------------------------------------------------------------

_cache_condition = threading.Condition()
_session_cache: dict = {}
_cache_version = 0  # incremented on each update


def _update_cache():
    """Refresh the session cache and notify SSE clients."""
    global _session_cache, _cache_version
    data = collect_sessions()
    with _cache_condition:
        _session_cache = data
        _cache_version += 1
        _cache_condition.notify_all()


def _get_cache() -> dict:
    with _cache_condition:
        return _session_cache.copy()


# ---------------------------------------------------------------------------
# File watcher (watchdog) + periodic refresh
# ---------------------------------------------------------------------------

_debounce_timer: threading.Timer | None = None
_debounce_lock = threading.Lock()
DEBOUNCE_SECONDS = 0.5
PERIODIC_INTERVAL = 5  # seconds — for PID/activity checks


def _debounced_update():
    """Schedule a cache update, debounced to avoid rapid-fire refreshes."""
    global _debounce_timer
    with _debounce_lock:
        if _debounce_timer is not None:
            _debounce_timer.cancel()
        _debounce_timer = threading.Timer(DEBOUNCE_SECONDS, _update_cache)
        _debounce_timer.daemon = True
        _debounce_timer.start()


def _periodic_refresh():
    """Periodically refresh the cache for PID/activity changes."""
    while True:
        time.sleep(PERIODIC_INTERVAL)
        _update_cache()


def _start_watcher():
    """Start file-watching (if watchdog available) and periodic refresh."""
    # Periodic refresh thread (always runs)
    periodic = threading.Thread(target=_periodic_refresh, daemon=True)
    periodic.start()

    if not HAS_WATCHDOG:
        print("  [info] watchdog not installed — using periodic-only mode (5s)")
        return

    class JNLHandler(FileSystemEventHandler):
        def on_modified(self, event):
            if event.src_path.endswith(".jsonl"):
                _debounced_update()

        def on_created(self, event):
            if event.src_path.endswith(".jsonl"):
                _debounced_update()

    observer = Observer()
    handler = JNLHandler()
    watched = 0
    for config_dir in CONFIG_DIRS:
        projects_dir = os.path.join(config_dir, "projects")
        if os.path.isdir(projects_dir):
            observer.schedule(handler, projects_dir, recursive=True)
            watched += 1

    if watched:
        observer.start()
        print(f"  [info] watchdog watching {watched} project dir(s)")
    else:
        print("  [info] no project dirs found to watch")


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------


def read_json(path: str):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def get_account_email(config_dir: str) -> str:
    # Try both possible config filenames
    for name in ("claude.json", ".claude.json"):
        cfg = read_json(os.path.join(config_dir, name))
        if cfg and "oauthAccount" in cfg:
            return cfg["oauthAccount"].get("emailAddress", "unknown")
    return os.path.basename(config_dir)


def is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError, OSError):
        return False
    # Guard against PID reuse: verify the process is actually Claude Code
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True, text=True, timeout=3,
        )
        cmd = result.stdout.strip().lower()
        return "claude" in cmd or "anthropic" in cmd
    except Exception:
        return True  # if we can't check, assume alive


def get_descendant_processes(pid: int) -> list[dict]:
    """Recursively get all descendant processes with pid, cpu, and command."""
    descendants = []
    try:
        result = subprocess.run(
            ["pgrep", "-P", str(pid)],
            capture_output=True, text=True, timeout=5,
        )
        child_pids = [int(p) for p in result.stdout.strip().split("\n") if p.strip()]
    except Exception:
        return descendants

    for cpid in child_pids:
        try:
            info = subprocess.run(
                ["ps", "-p", str(cpid), "-o", "pid=,pcpu=,command="],
                capture_output=True, text=True, timeout=5,
            )
            line = info.stdout.strip()
            if line:
                parts = line.split(None, 2)
                if len(parts) >= 3:
                    descendants.append({
                        "pid": int(parts[0]),
                        "cpu": float(parts[1]),
                        "command": parts[2],
                    })
                elif len(parts) == 2:
                    descendants.append({
                        "pid": int(parts[0]),
                        "cpu": float(parts[1]),
                        "command": "",
                    })
        except Exception:
            pass
        descendants.extend(get_descendant_processes(cpid))

    return descendants


def detect_activity_state(pid: int) -> str:
    """For a live session, determine actual activity from process tree.

    Returns: 'subagent' | 'hook' | 'thinking' | 'idle'
    """
    descendants = get_descendant_processes(pid)

    # Filter out noise processes (caffeinate, sleep, MCP servers, etc.)
    noise = ("caffeinate", "sleep")
    mcp_patterns = ("mcp-", "mcp_", "mongodb-mcp", "mcp-server", "mcp-gsheets",
                    "npx -y mongodb-mcp", "npm exec mcp", "op run -- npx")
    def is_noise(cmd: str) -> bool:
        low = cmd.lower()
        if any(n in low for n in noise):
            return True
        if any(p in low for p in mcp_patterns):
            return True
        return False
    meaningful = [d for d in descendants if not is_noise(d["command"])]

    # Check descendant commands for patterns
    hook_patterns = ("post-change", "hook", "biome", "tsc", "vitest", "eslint", "lint", "prettier", "pre-commit")
    for d in meaningful:
        cmd = d["command"].lower()
        # Subagent: another claude process spawned as child
        if "claude" in cmd:
            return "subagent"

    for d in meaningful:
        cmd = d["command"].lower()
        for pattern in hook_patterns:
            if pattern in cmd:
                return "hook"

    # If there are meaningful descendants that didn't match known patterns,
    # they're likely tool executions (bash, node scripts, etc.) — active work
    if meaningful:
        return "thinking"

    # No meaningful descendants — check main process CPU
    try:
        info = subprocess.run(
            ["ps", "-p", str(pid), "-o", "pcpu="],
            capture_output=True, text=True, timeout=5,
        )
        main_cpu = float(info.stdout.strip()) if info.stdout.strip() else 0.0
        if main_cpu > 5.0:
            return "thinking"
    except Exception:
        pass

    return "idle"


def find_all_claude_pids() -> set[int]:
    """Find all running claude/node processes that look like Claude Code sessions."""
    pids = set()
    try:
        result = subprocess.run(
            ["ps", "aux"], capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.split("\n"):
            if "claude" in line.lower() and ("node" in line or "claude" in line):
                parts = line.split()
                if len(parts) > 1:
                    try:
                        pids.add(int(parts[1]))
                    except ValueError:
                        pass
    except Exception:
        pass
    return pids


def tail_lines(path: str, n: int = TODO_SCAN_LINES) -> list[str]:
    """Read the last *n* lines of a file by seeking from the end in chunks."""
    chunk_size = 65536  # 64 KB
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)  # seek to end
            size = f.tell()
            if size == 0:
                return []
            buf = b""
            pos = size
            while pos > 0:
                read_size = min(chunk_size, pos)
                pos -= read_size
                f.seek(pos)
                buf = f.read(read_size) + buf
                if buf.count(b"\n") > n:
                    break
            lines = buf.decode("utf-8", errors="replace").split("\n")
            # Strip trailing empty element from final newline
            if lines and not lines[-1]:
                lines = lines[:-1]
            return lines[-n:]
    except Exception:
        return []


def extract_last_todo(lines: list[str]) -> list[dict] | None:
    for line in reversed(lines):
        if "TodoWrite" not in line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        content = (obj.get("message") or {}).get("content", [])
        if isinstance(content, str):
            continue
        for block in content:
            if block.get("type") == "tool_use" and block.get("name") == "TodoWrite":
                todos = block.get("input", {}).get("todos", [])
                if todos:
                    return todos
    return None


def extract_last_user_message(lines: list[str]) -> str | None:
    for line in reversed(lines):
        if '"role":"user"' not in line and '"role": "user"' not in line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") != "user":
            continue
        content = (obj.get("message") or {}).get("content", [])
        if isinstance(content, str):
            return content[:200]
        for block in content:
            if block.get("type") == "text" and block.get("text", "").strip():
                return block["text"].strip()[:200]
    return None


def extract_last_assistant_text(lines: list[str]) -> str | None:
    for line in reversed(lines):
        if '"role":"assistant"' not in line and '"role": "assistant"' not in line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") != "assistant":
            continue
        content = (obj.get("message") or {}).get("content", [])
        if isinstance(content, str):
            return content[:500]
        for block in reversed(content if isinstance(content, list) else []):
            if block.get("type") == "text" and block.get("text", "").strip():
                return block["text"].strip()[:500]
    return None


def extract_current_activity(lines: list[str]) -> str | None:
    """Extract a human-readable description of the last tool Claude invoked."""
    for line in reversed(lines):
        if '"role":"assistant"' not in line and '"role": "assistant"' not in line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") != "assistant":
            continue
        content = (obj.get("message") or {}).get("content", [])
        if not isinstance(content, list):
            return None
        # Find the last tool_use block in this assistant message
        last_tool = None
        for block in content:
            if block.get("type") == "tool_use":
                last_tool = block
        if not last_tool:
            return None
        name = last_tool.get("name", "")
        inp = last_tool.get("input", {})
        if not isinstance(inp, dict):
            inp = {}
        return _format_tool_activity(name, inp)
    return None


def _format_tool_activity(name: str, inp: dict) -> str | None:
    """Map a tool name + input to a short human-readable activity string."""
    if name == "Edit":
        fp = inp.get("file_path", "")
        return f"Editing {_short_path(fp)}" if fp else "Editing a file"
    if name == "Write":
        fp = inp.get("file_path", "")
        return f"Writing {_short_path(fp)}" if fp else "Writing a file"
    if name == "Read":
        fp = inp.get("file_path", "")
        return f"Reading {_short_path(fp)}" if fp else "Reading a file"
    if name == "Bash":
        cmd = inp.get("command", "")
        return f"Running: {cmd[:80]}" if cmd else "Running a command"
    if name == "Grep":
        pat = inp.get("pattern", "")
        return f'Searching for "{pat[:60]}"' if pat else "Searching"
    if name == "Glob":
        pat = inp.get("pattern", "")
        return f"Finding files: {pat[:60]}" if pat else "Finding files"
    if name == "Agent":
        desc = inp.get("description", inp.get("prompt", "")[:80])
        return f"Subagent: {desc[:80]}" if desc else "Running subagent"
    if name == "Skill":
        skill = inp.get("skill", "")
        return f"Using skill: {skill}" if skill else "Using a skill"
    if name in ("WebFetch", "WebSearch"):
        return "Browsing web"
    if name in ("TodoWrite", "TaskCreate", "TaskUpdate"):
        return "Updating tasks"
    if name == "AskUserQuestion":
        return "Asking user a question"
    # MCP tools: strip mcp__server__prefix to show just the action
    if name.startswith("mcp__"):
        parts = name.split("__")
        short = parts[-1] if len(parts) >= 3 else name
        return f"Using {short}"
    return f"Using {name}" if name else None


def _short_path(fp: str) -> str:
    """Shorten an absolute path to ~last 3 segments for display."""
    if not fp:
        return fp
    if fp.startswith("/Users/"):
        segments = fp.split("/")
        if len(segments) > 2:
            fp = "~/" + "/".join(segments[3:])
    parts = fp.split("/")
    return "/".join(parts[-3:]) if len(parts) > 3 else fp


def get_session_topic(jsonl_path: str) -> str | None:
    try:
        with open(jsonl_path) as f:
            for line in f:
                if '"role":"user"' not in line and '"role": "user"' not in line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") != "user":
                    continue
                content = (obj.get("message") or {}).get("content", [])
                if isinstance(content, str):
                    return content[:200]
                for block in content:
                    if block.get("type") == "text" and block.get("text", "").strip():
                        return block["text"].strip()[:200]
    except Exception:
        pass
    return None


def get_last_timestamp(lines: list[str]) -> str | None:
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
            ts = obj.get("timestamp")
            if ts:
                return ts
        except json.JSONDecodeError:
            continue
    return None


def detect_session_state(lines: list[str]) -> str:
    """Determine the conversational state of a live session from its JSONL tail.

    Returns one of:
        "questioning" – Claude is asking the user a multi-choice question via
                        AskUserQuestion (either pending call or active).
        "approving" – Claude requested a tool_use and is waiting for the user
                      to approve (or deny) it before proceeding.
        "waiting"   – Claude finished responding; waiting for user input.
        "thinking"  – Claude is generating a response (last entry is a user
                      message or a tool_result fed back to Claude).
        "unknown"   – cannot determine (e.g. empty transcript).
    """
    RECENCY_THRESHOLD = 2  # seconds — if newer, assume still streaming

    # Track whether the most recent non-skipped entry was a local_command
    # system entry — if so, the user message that triggered it should also
    # be skipped (it was a slash command, already handled).
    saw_local_command = False

    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg_type = obj.get("type")

        # Skip metadata-only entries that don't affect state
        if msg_type in ("file-history-snapshot", "attachment", "custom-title",
                        "agent-name", "permission-mode"):
            continue

        # system entries with subtype "local_command" mean a slash command
        # was executed.  Mark it so we skip the triggering user message.
        if msg_type == "system" and obj.get("subtype") == "local_command":
            saw_local_command = True
            continue

        if msg_type == "assistant":
            # Synthetic messages (e.g. "No response requested." after session
            # resume) are harness-generated, not real Claude output — but they
            # DO indicate Claude has finished responding. If this is the first
            # conversational entry we encounter (after skipping metadata), return
            # "waiting" because Claude has wrapped up.
            model = (obj.get("message") or {}).get("model", "")
            if model == "<synthetic>":
                # Synthetic message is the last real conversational entry —
                # Claude has finished and is waiting for user input.
                return "waiting"

            content = (obj.get("message") or {}).get("content", [])
            if isinstance(content, str):
                return "waiting"

            has_tool_use = any(
                b.get("type") == "tool_use" for b in content if isinstance(b, dict)
            )
            if has_tool_use:
                # Check if any tool_use is AskUserQuestion (high priority).
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "AskUserQuestion":
                        return "questioning"
                # Assistant requested a tool — the next entry should be a
                # tool_result (type "user").  Since we're scanning from the
                # end, there is no subsequent tool_result yet → the session
                # is blocked on user approval (or the tool is executing).
                return "approving"

            # Text-only assistant message — might be a split entry that will
            # be followed by a tool_use.  Check timestamp recency.
            ts = obj.get("timestamp")
            if ts:
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    age = (datetime.now(timezone.utc) - dt).total_seconds()
                    if age < RECENCY_THRESHOLD:
                        return "thinking"  # too recent, probably still streaming
                except Exception:
                    pass
            return "waiting"

        if msg_type == "user":
            # IDE background events are logged as user messages but Claude
            # may silently consume them without producing a reply.  Skip
            # these so we find the real last conversational entry.
            content = (obj.get("message") or {}).get("content", [])
            text = ""
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "")
                        break
            skip_tags = ("<ide_opened_file>", "<ide_action>", "<ide_closed_file>",
                         "<ide_active_file>", "<ide_selection>",
                         "<local-command-caveat>", "<local-command-stdout>",
                         "<command-name>", "<command-message>", "<command-args>")
            if any(text.strip().startswith(tag) for tag in skip_tags):
                continue  # skip IDE/local-command event, keep scanning

            # If we previously saw a local_command system entry, this user
            # message is the slash command that triggered it — skip it.
            if saw_local_command:
                saw_local_command = False
                continue

            # User interrupted a tool call — Claude is waiting for new input,
            # not processing this message.
            if text.strip() == "[Request interrupted by user for tool use]":
                return "waiting"

            # Check if this is a tool_result and there are still unmatched
            # tool_use calls (parallel tool calls where not all results are
            # back yet).  If so, the session is still waiting for approval
            # on outstanding tools.
            is_tool_result = isinstance(content, list) and any(
                isinstance(b, dict) and b.get("type") == "tool_result"
                for b in content
            )
            if is_tool_result:
                # Check if any tool_result contains a tool_reference to AskUserQuestion.
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        result_content = block.get("content", [])
                        if isinstance(result_content, list):
                            for cb in result_content:
                                if (isinstance(cb, dict)
                                    and cb.get("type") == "tool_reference"
                                    and cb.get("tool_name") == "AskUserQuestion"):
                                    return "questioning"

                # User rejected/interrupted a tool call — Claude is waiting
                # for new input, not processing this result.
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("is_error"):
                        rc = block.get("content", "")
                        reject_text = rc if isinstance(rc, str) else ""
                        if not reject_text and isinstance(rc, list):
                            for cb in rc:
                                if isinstance(cb, dict) and cb.get("type") == "text":
                                    reject_text = cb.get("text", "")
                                    break
                        if "The user doesn't want to proceed with this tool use" in reject_text:
                            return "waiting"

                tool_use_ids = set()
                tool_result_ids = set()
                for prev_line in lines:
                    if not prev_line.strip():
                        continue
                    try:
                        prev = json.loads(prev_line)
                    except json.JSONDecodeError:
                        continue
                    prev_content = (prev.get("message") or {}).get("content", [])
                    if not isinstance(prev_content, list):
                        continue
                    for b in prev_content:
                        if not isinstance(b, dict):
                            continue
                        if b.get("type") == "tool_use":
                            tool_use_ids.add(b.get("id"))
                        elif b.get("type") == "tool_result":
                            tool_result_ids.add(b.get("tool_use_id"))
                if tool_use_ids - tool_result_ids:
                    return "approving"

            # Real user message or tool_result → Claude should be responding.
            return "thinking"

        # Skip non-conversation entries (system, file-history-snapshot, etc.)
        continue

    return "unknown"


def _is_plan_approval_pending(lines: list[str]) -> bool:
    """Check if the session is in plan mode waiting for plan approval.

    Returns True only when the last permission-mode entry is "plan" AND
    there's no real (non-synthetic) assistant activity after it — which
    would indicate the plan was already approved and Claude continued
    working.
    """
    skip_types = ("file-history-snapshot", "attachment", "custom-title",
                  "agent-name")
    found_plan_mode = False
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg_type = obj.get("type")
        if msg_type in skip_types:
            continue
        if msg_type == "permission-mode":
            if obj.get("permissionMode") == "plan":
                found_plan_mode = True
            # Any permission-mode entry (plan or otherwise) is definitive.
            break
        # Any assistant activity after the permission-mode entry means
        # the plan was already approved/completed.  This includes synthetic
        # messages (e.g. "No response requested" after session end) — they
        # indicate the turn finished, so plan approval is not pending.
        if msg_type == "assistant":
            # Synthetic messages (e.g. "No response requested." after resume)
            # are not real assistant activity — skip them.
            model = (obj.get("message") or {}).get("model", "")
            if model == "<synthetic>":
                continue
            return False
        # User messages, system entries, etc. — keep scanning past them
        # to find the permission-mode entry.
        continue
    return found_plan_mode


def _last_entry_is_user(lines: list[str]) -> bool:
    """Check if the last meaningful conversational JSONL entry is a user message.

    Returns True if the last non-metadata entry is a user message (plain text
    or tool_result).  When this is the case, Claude is processing the user's
    input — the idle-JSONL heuristic should not downgrade to "approving"
    because the idleness is API latency, not a blocked permission prompt.
    """
    skip_types = ("system", "attachment", "file-history-snapshot",
                  "custom-title", "agent-name", "permission-mode")
    skip_tags = ("<ide_opened_file>", "<ide_action>", "<ide_closed_file>",
                 "<ide_active_file>", "<ide_selection>",
                 "<local-command-caveat>", "<local-command-stdout>",
                 "<command-name>", "<command-message>", "<command-args>")
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg_type = obj.get("type")
        if msg_type in skip_types:
            continue
        # Skip synthetic assistant messages (harness-generated wrap-ups)
        if msg_type == "assistant":
            model = (obj.get("message") or {}).get("model", "")
            if model == "<synthetic>":
                continue
            # Hit a real assistant message — stop scanning
            return False
        if msg_type == "user":
            content = (obj.get("message") or {}).get("content", [])
            # Skip IDE/local-command background events
            text = ""
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "")
                        break
            if any(text.strip().startswith(tag) for tag in skip_tags):
                continue
            # Found a real user entry (text or tool_result).
            return True
        # Any other conversational type — stop scanning
        return False
    return False


def _last_entry_is_synthetic(lines: list[str]) -> bool:
    """Check if the last meaningful conversational JSONL entry is synthetic.

    Returns True if the most recent non-metadata entry is an assistant
    message with model="<synthetic>".  When a session is resumed after
    interruption, the synthetic "No response requested." message is the
    last entry — but Claude may already be in a new turn showing an
    approval prompt whose tool_use hasn't been written yet.
    """
    skip_types = ("system", "attachment", "file-history-snapshot",
                  "custom-title", "agent-name", "permission-mode")
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg_type = obj.get("type")
        if msg_type in skip_types:
            continue
        if msg_type == "assistant":
            model = (obj.get("message") or {}).get("model", "")
            return model == "<synthetic>"
        return False
    return False


def _synthetic_follows_rejection(lines: list[str]) -> bool:
    """Check if the trailing synthetic message follows a user rejection/interruption.

    When a user rejects a tool call, the JSONL ends with a tool_result
    error ("The user doesn't want to proceed...") and/or a user text
    "[Request interrupted by user for tool use]", followed by metadata
    entries and a synthetic assistant message.  In this case the session
    is genuinely done — not blocked on a new approval prompt.
    """
    skip_types = ("system", "attachment", "file-history-snapshot",
                  "custom-title", "agent-name", "permission-mode")
    found_synthetic = False
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg_type = obj.get("type")
        if msg_type in skip_types:
            continue
        if not found_synthetic:
            # First real entry should be the synthetic assistant message.
            if msg_type == "assistant":
                model = (obj.get("message") or {}).get("model", "")
                if model == "<synthetic>":
                    found_synthetic = True
                    continue
            return False
        # Found synthetic — now check what precedes it.
        if msg_type == "user":
            content = (obj.get("message") or {}).get("content", [])
            text = ""
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "")
                        break
                    if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("is_error"):
                        rc = block.get("content", "")
                        reject_text = rc if isinstance(rc, str) else ""
                        if not reject_text and isinstance(rc, list):
                            for cb in rc:
                                if isinstance(cb, dict) and cb.get("type") == "text":
                                    reject_text = cb.get("text", "")
                                    break
                        if "The user doesn't want to proceed" in reject_text:
                            return True
            if "[Request interrupted by user for tool use]" in text:
                return True
        return False
    return False


def get_git_branch(lines: list[str]) -> str | None:
    for line in reversed(lines):
        if "gitBranch" not in line:
            continue
        try:
            obj = json.loads(line)
            branch = obj.get("gitBranch")
            if branch:
                return branch
        except json.JSONDecodeError:
            continue
    return None


def get_permission_mode(lines: list[str]) -> str | None:
    # When the permission-mode entry says "plan", verify the session is
    # still in plan mode by checking for write/edit tool_use after it.
    # Claude Code doesn't always write a permission-mode entry when
    # exiting plan mode, so assistant messages using editing tools
    # (Write, Edit, Bash, etc.) imply plan was approved → acceptEdits.
    # ExitPlanMode is the definitive signal that plan mode ended;
    # edit tools are a fallback for when no explicit exit was written.
    PLAN_EXIT_TOOLS = {"Write", "Edit", "Bash", "NotebookEdit", "ExitPlanMode"}
    for idx in range(len(lines) - 1, -1, -1):
        line = lines[idx]
        if "permissionMode" not in line:
            continue
        try:
            obj = json.loads(line)
            if obj.get("type") != "permission-mode":
                continue
            mode = obj.get("permissionMode")
            if not mode:
                continue
            if mode != "plan":
                return mode
            # Mode is "plan" — check if there are editing tool_use calls
            # after this entry, which would mean the plan was approved.
            for later_line in lines[idx + 1:]:
                try:
                    later_obj = json.loads(later_line)
                except json.JSONDecodeError:
                    continue
                later_msg = later_obj.get("message", {})
                if later_msg.get("role") != "assistant":
                    continue
                content = later_msg.get("content", [])
                if not isinstance(content, list):
                    continue
                for b in content:
                    if (isinstance(b, dict) and b.get("type") == "tool_use"
                            and b.get("name") in PLAN_EXIT_TOOLS):
                        return "acceptEdits"
            return "plan"
        except json.JSONDecodeError:
            continue
    return None


def find_parent_app(pid: int) -> str | None:
    """Walk up the process tree from *pid* to find the owning GUI application."""
    known_apps = {
        "warp": "Warp",
        "code": "Visual Studio Code",
        "code helper": "Visual Studio Code",
        "electron": "Visual Studio Code",  # VS Code is Electron
        "claude": "Claude",
        "terminal": "Terminal",
        "iterm2": "iTerm2",
    }
    try:
        # Start from the parent of the given PID — the PID itself is the
        # claude CLI, which would falsely match the "Claude" desktop app.
        boot = subprocess.run(
            ["ps", "-p", str(pid), "-o", "ppid="],
            capture_output=True, text=True, timeout=3,
        )
        current = int(boot.stdout.strip()) if boot.stdout.strip() else pid
        visited = set()
        while current and current > 1 and current not in visited:
            visited.add(current)
            result = subprocess.run(
                ["ps", "-p", str(current), "-o", "ppid=,comm="],
                capture_output=True, text=True, timeout=3,
            )
            line = result.stdout.strip()
            if not line:
                break
            parts = line.split(None, 1)
            if len(parts) < 2:
                break
            ppid = int(parts[0])
            comm = parts[1].strip().lower()
            # Check against known apps
            for key, app_name in known_apps.items():
                if key in comm:
                    return app_name
            current = ppid
    except Exception:
        pass
    return None


def focus_warp_tab(session_name: str) -> dict:
    """Focus the Warp tab whose title contains *session_name* (or 'Claude Code')."""
    match_term = session_name if session_name else "Claude Code"
    # Escape backslashes and double-quotes for AppleScript string literal
    safe_term = match_term.replace("\\", "\\\\").replace('"', '\\"')

    apple_script = f'''
        tell application "Warp" to activate
        delay 0.3
        tell application "System Events"
            tell process "Warp"
                set winCount to count of windows

                -- Phase 1: check every window's *current* tab (no cycling)
                repeat with i from 1 to winCount
                    if name of window i contains "{safe_term}" then
                        perform action "AXRaise" of window i
                        return "found:" & name of window i
                    end if
                end repeat

                -- Phase 2: cycle tabs in the front window
                set fw to window 1
                set initialName to name of fw
                repeat 20 times
                    key code 30 using {{command down, shift down}}
                    delay 0.15
                    set curName to name of fw
                    if curName is initialName then exit repeat
                    if curName contains "{safe_term}" then return "found:" & curName
                end repeat

                -- Phase 3: raise each non-front window and cycle its tabs
                repeat with i from 2 to winCount
                    set targetWin to window i
                    perform action "AXRaise" of targetWin
                    delay 0.2
                    set initialName to name of window 1
                    repeat 20 times
                        key code 30 using {{command down, shift down}}
                        delay 0.15
                        set curName to name of window 1
                        if curName is initialName then exit repeat
                        if curName contains "{safe_term}" then return "found:" & curName
                    end repeat
                end repeat

                return "not_found"
            end tell
        end tell
    '''
    try:
        result = subprocess.run(
            ["osascript", "-e", apple_script],
            capture_output=True, text=True, timeout=15,
        )
        output = result.stdout.strip()
        if output.startswith("found:"):
            tab_name = output[6:]
            return {"ok": True, "action": "focused", "detail": f"Focused tab: {tab_name}"}
        return {"ok": False, "action": "not_found",
                "detail": f"No Warp tab matching '{match_term}'"}
    except Exception as e:
        return {"ok": False, "action": "error", "detail": str(e)}


def open_session(session_id: str, config_dir: str, pid: int | None, alive: bool,
                 session_name: str = "") -> dict:
    """Open / focus a session.  Returns {ok, action, detail}."""
    if alive and pid:
        app = find_parent_app(pid)
        if app == "Warp":
            return focus_warp_tab(session_name)
        elif app:
            script = f'tell application "{app}" to activate'
            try:
                subprocess.run(
                    ["osascript", "-e", script],
                    capture_output=True, text=True, timeout=5,
                )
                return {"ok": True, "action": "activated", "detail": f"Brought {app} to front"}
            except Exception as e:
                return {"ok": False, "action": "error", "detail": str(e)}
        else:
            return {"ok": False, "action": "unknown_app",
                    "detail": "Session is running but couldn't identify the host app"}

    # Session not running — resume in Warp
    # Build the claude resume command with the right config dir
    default_dir = os.path.expanduser("~/.claude")
    env_prefix = ""
    if config_dir != default_dir:
        env_prefix = f"CLAUDE_CONFIG_DIR={config_dir} "

    # Use osascript to open a new Warp tab and run the resume command
    resume_cmd = f"{env_prefix}claude --resume {session_id}"
    apple_script = f'''
        tell application "Warp" to activate
        delay 0.3
        tell application "System Events"
            tell process "Warp"
                keystroke "t" using command down
                delay 0.3
                keystroke "{resume_cmd}"
                key code 36
            end tell
        end tell
    '''
    try:
        subprocess.run(
            ["osascript", "-e", apple_script],
            capture_output=True, text=True, timeout=10,
        )
        return {"ok": True, "action": "resumed", "detail": "Resuming in new Warp tab"}
    except Exception as e:
        return {"ok": False, "action": "error", "detail": str(e)}


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


def collect_sessions() -> dict:
    accounts = []

    for config_dir in CONFIG_DIRS:
        if not os.path.isdir(config_dir):
            continue

        email = get_account_email(config_dir)
        sessions_index_dir = os.path.join(config_dir, "sessions")
        projects_dir = os.path.join(config_dir, "projects")

        pid_map = {}
        all_claude_pids = find_all_claude_pids()
        if os.path.isdir(sessions_index_dir):
            for f in glob.glob(os.path.join(sessions_index_dir, "*.json")):
                data = read_json(f)
                if data and "sessionId" in data:
                    sid = data["sessionId"]
                    pid = data.get("pid")
                    alive = is_pid_alive(pid) if pid else False
                    try:
                        mtime = os.path.getmtime(f)
                    except OSError:
                        mtime = 0
                    data["_alive"] = alive
                    data["_mtime"] = mtime
                    existing = pid_map.get(sid)
                    if existing is None:
                        pid_map[sid] = data
                    else:
                        # Prefer alive PID; among equals, prefer most recently modified index file
                        if alive and not existing["_alive"] or alive == existing["_alive"] and mtime > existing["_mtime"]:
                            pid_map[sid] = data

        sessions = []
        if os.path.isdir(projects_dir):
            for project_dir in sorted(os.listdir(projects_dir)):
                full_project = os.path.join(projects_dir, project_dir)
                if not os.path.isdir(full_project):
                    continue

                for jsonl_file in glob.glob(os.path.join(full_project, "*.jsonl")):
                    session_id = os.path.basename(jsonl_file).replace(".jsonl", "")

                    try:
                        file_mtime = os.path.getmtime(jsonl_file)
                    except OSError:
                        file_mtime = 0

                    if time.time() - file_mtime > 7 * 86400:
                        continue

                    lines = tail_lines(jsonl_file, TODO_SCAN_LINES)
                    last_ts = get_last_timestamp(lines)
                    todos = extract_last_todo(lines)
                    git_branch = get_git_branch(lines)
                    permission_mode = get_permission_mode(lines)
                    topic = get_session_topic(jsonl_file)
                    last_user_msg = extract_last_user_message(lines)
                    last_assistant_text = extract_last_assistant_text(lines)
                    session_state = detect_session_state(lines)

                    pid_info = pid_map.get(session_id, {})
                    pid = pid_info.get("pid")
                    cwd = pid_info.get("cwd", "")
                    kind = pid_info.get("kind", "")
                    session_name = pid_info.get("name", "")
                    alive = is_pid_alive(pid) if pid else False

                    # Also check if the PID (or its parent) is among running claude procs
                    if not alive and pid:
                        alive = pid in all_claude_pids

                    if alive:
                        activity = detect_activity_state(pid) if pid else "idle"
                        if activity == "subagent":
                            status = "subagent"
                        elif activity == "hook":
                            status = "hook"
                        elif session_state == "questioning":
                            # AskUserQuestion is blocking — the process is idle waiting
                            # for user input.  Not a tool approval, so never downgrade.
                            status = "questioning"
                        elif session_state == "approving":
                            # tool_use in JSONL without tool_result could mean
                            # waiting for user approval OR the tool is currently
                            # executing.  If the process tree shows active child
                            # processes, the tool is running — not blocked.
                            status = "thinking" if activity == "thinking" else "approving"
                        elif activity == "thinking" or session_state == "thinking":
                            if session_state == "thinking" and activity == "idle":
                                # During LLM inference the node process appears idle
                                # (waiting on API HTTP response, no child processes,
                                # low CPU).  Use JSONL recency to distinguish "still
                                # processing" from "finished but waiting for input".
                                # If the file was written recently (<10s), Claude is
                                # likely still working.
                                #
                                # Exception: if the last entry is a user message
                                # (text or tool_result), Claude is processing user
                                # input — the idleness is API latency, not a
                                # blocked permission prompt.  But if the file is
                                # very stale (>30s), Claude has almost certainly
                                # finished processing and is blocked on approval.
                                last_is_user = _last_entry_is_user(lines)
                                jsonl_age = time.time() - file_mtime
                                if jsonl_age > 10 and not last_is_user:
                                    # Claude was mid-turn but hasn't written anything
                                    # in >10s while the process is idle — most likely
                                    # blocked on a permission prompt (the pending
                                    # tool_use hasn't been written to JSONL yet).
                                    # If Claude had finished, there'd be a real
                                    # assistant entry making session_state "waiting".
                                    status = "approving"
                                elif last_is_user and jsonl_age > 30:
                                    # Last entry is a user message (text or tool_result)
                                    # but JSONL hasn't been written to in >30s — Claude
                                    # likely already processed it and is now blocked on
                                    # a permission prompt for a new tool_use that hasn't
                                    # been written to JSONL yet.
                                    status = "approving"
                                else:
                                    status = "thinking"
                            else:
                                status = "thinking"
                        else:
                            # After a session resume, the last JSONL entry is a
                            # synthetic "No response requested." — but Claude may
                            # already be in a new turn blocked on an approval
                            # prompt whose tool_use hasn't been written yet.
                            # Detect this by checking if the "waiting" came from
                            # a synthetic entry on an alive, idle process.
                            if (activity == "idle"
                                    and _last_entry_is_synthetic(lines)
                                    and not _synthetic_follows_rejection(lines)):
                                status = "approving"
                            else:
                                status = "waiting"
                        # Plan mode: the interview UI asks the user
                        # multi-choice questions — semantically "questioning".
                        # Only apply when plan is actually pending: the
                        # permission-mode entry says "plan" AND there's no
                        # real assistant work after it.
                        if status in ("waiting", "thinking") and _is_plan_approval_pending(lines):
                            status = "questioning"
                    elif last_ts:
                        try:
                            dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
                            age_secs = (datetime.now(timezone.utc) - dt).total_seconds()
                            if age_secs < 300:
                                status = "recent"
                            elif age_secs < 7200:
                                # 2 hours — generous for sessions waiting for input
                                status = "idle"
                            else:
                                status = "inactive"
                        except Exception:
                            status = "unknown"
                    else:
                        status = "unknown"

                    try:
                        file_size = os.path.getsize(jsonl_file)
                    except OSError:
                        file_size = 0

                    # When JSONL is stale (>60s), the last user message may
                    # be from a previous turn — flag it but still show it,
                    # since a stale message is more useful than nothing.
                    user_msg_stale = alive and time.time() - file_mtime > 60

                    current_activity = extract_current_activity(lines) if alive else None

                    # Merge in user annotations
                    ann = get_annotation(session_id)

                    sessions.append({
                        "session_id": session_id,
                        "session_name": session_name,
                        "project": friendly_project_name(project_dir),
                        "cwd": cwd,
                        "status": status,
                        "pid": pid,
                        "alive": alive,
                        "config_dir": config_dir,
                        "last_activity": last_ts,
                        "last_activity_ago": time_ago(last_ts) if last_ts else "unknown",
                        "topic": topic,
                        "last_user_msg": last_user_msg,
                        "user_msg_stale": user_msg_stale,
                        "last_assistant_text": last_assistant_text,
                        "current_activity": current_activity,
                        "git_branch": git_branch,
                        "permission_mode": permission_mode,
                        "kind": kind,
                        "todos": todos,
                        "file_size_kb": round(file_size / 1024, 1),
                        "jsonl_path": jsonl_file,
                        "user_notes": ann.get("notes", ""),
                        "user_todos": ann.get("todos", []),
                    })

        sessions = [s for s in sessions if s["status"] not in ("inactive", "unknown")]

        status_order = {
            "questioning": 0,
            "approving": 0,
            "waiting": 1,
            "thinking": 2,
            "subagent": 2,
            "hook": 2,
            "recent": 3,
            "idle": 4,
        }
        sessions.sort(key=lambda s: (
            status_order.get(s["status"], 5),
            -(datetime.fromisoformat(s["last_activity"].replace("Z", "+00:00")).timestamp()
              if s["last_activity"] else 0),
        ))

        accounts.append({
            "email": email,
            "config_dir": config_dir,
            "sessions": sessions,
        })

    return {
        "accounts": accounts,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# HTTP Server
# ---------------------------------------------------------------------------


class DashboardHandler(http.server.BaseHTTPRequestHandler):

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/api/sessions":
            data = _get_cache()
            self._json_response(200, data)

        elif parsed.path == "/api/events":
            self._handle_sse()

        elif parsed.path.startswith("/api/annotations/"):
            session_id = parsed.path.split("/api/annotations/", 1)[1]
            ann = get_annotation(session_id)
            self._json_response(200, ann)

        else:
            # Serve from React build (client/dist/)
            dist_dir = Path(__file__).parent.parent / "client" / "dist"
            rel_path = parsed.path.lstrip("/")
            if not rel_path:
                rel_path = "index.html"
            candidate = dist_dir / rel_path
            if candidate.exists() and candidate.is_file():
                import mimetypes
                mime, _ = mimetypes.guess_type(str(candidate))
                self.send_response(200)
                self.send_header("Content-Type", mime or "application/octet-stream")
                if candidate.name == "index.html":
                    self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(candidate.read_bytes())
            else:
                # SPA fallback: serve index.html for unmatched routes
                index = dist_dir / "index.html"
                if index.exists():
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(index.read_bytes())
                else:
                    self._json_response(404, {"error": "React build not found. Run: cd claude-dashboard && npm run build"})

    def do_POST(self):
        parsed = urlparse(self.path)

        if parsed.path.startswith("/api/open/"):
            session_id = parsed.path.split("/api/open/", 1)[1]
            # Find the session in cached data
            data = _get_cache()
            target = None
            for acct in data["accounts"]:
                for s in acct["sessions"]:
                    if s["session_id"] == session_id:
                        target = s
                        break
                if target:
                    break

            if not target:
                self._json_response(404, {"ok": False, "detail": "Session not found"})
                return

            result = open_session(
                session_id=session_id,
                config_dir=target.get("config_dir", ""),
                pid=target.get("pid"),
                alive=target.get("alive", False),
                session_name=target.get("session_name", ""),
            )
            self._json_response(200, result)
        else:
            self._json_response(404, {"error": "not found"})

    def do_PUT(self):
        parsed = urlparse(self.path)

        if parsed.path.startswith("/api/annotations/"):
            session_id = parsed.path.split("/api/annotations/", 1)[1]
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                data = json.loads(body)
                set_annotation(session_id, {
                    "notes": data.get("notes", ""),
                    "todos": data.get("todos", []),
                })
                self._json_response(200, {"ok": True})
            except (json.JSONDecodeError, Exception) as e:
                self._json_response(400, {"error": str(e)})
        else:
            self._json_response(404, {"error": "not found"})

    def _handle_sse(self):
        """Server-Sent Events endpoint — streams session data to clients."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        last_version = 0
        try:
            while True:
                with _cache_condition:
                    # Wait for new data or timeout (keepalive)
                    _cache_condition.wait(timeout=30)
                    current_version = _cache_version
                    data = _session_cache

                if current_version > last_version and data:
                    last_version = current_version
                    payload = json.dumps(data)
                    self.wfile.write(f"event: sessions\ndata: {payload}\n\n".encode())
                    self.wfile.flush()
                else:
                    # Send keepalive comment
                    self.wfile.write(b":keepalive\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # Client disconnected

    def _json_response(self, code, obj):
        payload = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        pass


class ThreadingHTTPServer(http.server.ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    print("\n  Claude Sessions Dashboard")
    print("  ─────────────────────────")
    print(f"  Watching:     {', '.join(CONFIG_DIRS)}")
    print(f"  Open:         http://localhost:{PORT}")
    print(f"  Annotations:  {ANNOTATIONS_FILE}")
    print(f"  Watchdog:     {'active' if HAS_WATCHDOG else 'not installed (periodic-only mode)'}")
    print("  Press Ctrl+C to stop\n")

    # Initial cache population
    _update_cache()

    # Start file watcher and periodic refresh
    _start_watcher()

    server = ThreadingHTTPServer(("", PORT), DashboardHandler)

    def shutdown_handler(signum, frame):
        print("\n  Shutting down...")
        server.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown_handler)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.")
        server.shutdown()
        sys.exit(0)


if __name__ == "__main__":
    main()
