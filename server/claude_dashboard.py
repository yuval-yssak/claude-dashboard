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
# Extracted modules — see server/ARCHITECTURE.md (in progress) for the layout.
# Bare-name re-imports keep the rest of this file working unchanged while the
# refactor proceeds incrementally.
# ---------------------------------------------------------------------------

from annotations import (  # noqa: E402
    get_annotation,
    load_annotations,
    set_annotation,
)
from config import (  # noqa: E402
    ANNOTATIONS_FILE,
    CONFIG_DIRS,
    DEBOUNCE_SECONDS,
    PERIODIC_INTERVAL,
    PORT,
    TODO_SCAN_LINES,
)
from jsonl_scan import (  # noqa: E402
    extract_current_activity,
    extract_cwd,
    extract_last_assistant_model_and_thinking,
    extract_last_assistant_text,
    extract_last_todo,
    extract_last_user_message,
    extract_plan_file_path,
    get_git_branch,
    get_last_timestamp,
    get_session_title,
    get_session_topic,
    tail_lines,
)
from process_monitor import (  # noqa: E402
    detect_activity_state,
    find_all_claude_pids,
    is_pid_alive,
)
from query_helpers import get_account_email, get_rate_limits, read_json  # noqa: E402
from utils import abbreviate_home, friendly_project_name, time_ago  # noqa: E402

# Load annotations on startup (was _load_annotations() in the monolith).
load_annotations()

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
            if event.src_path.endswith(".jsonl") or event.src_path.endswith("rate-limits.json"):
                _debounced_update()

        def on_created(self, event):
            if event.src_path.endswith(".jsonl") or event.src_path.endswith("rate-limits.json"):
                _debounced_update()

    observer = Observer()
    handler = JNLHandler()
    watched = 0
    for config_dir in CONFIG_DIRS:
        # Watch config dir root for rate-limits.json changes
        if os.path.isdir(config_dir):
            observer.schedule(handler, config_dir, recursive=False)
            watched += 1
        # Watch projects dir for JSONL changes
        projects_dir = os.path.join(config_dir, "projects")
        if os.path.isdir(projects_dir):
            observer.schedule(handler, projects_dir, recursive=True)
            watched += 1

    if watched:
        observer.start()
        print(f"  [info] watchdog watching {watched} project dir(s)")
    else:
        print("  [info] no project dirs found to watch")


# Data helpers, process monitoring, and JSONL scanning live in
# query_helpers.py, process_monitor.py, and jsonl_scan.py respectively.


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

            # Claude writes thinking and tool_use as two separate JSONL entries.
            # The thinking entry is flushed first, often with stop_reason still
            # absent — the terminal stop_reason only lands on the tool_use entry.
            # Fast-path from 4c1b66f (stop_reason == "tool_use") therefore misses
            # the common case and the scanner falls through to "thinking", hiding
            # real approvals and AskUserQuestion prompts from the user.
            has_thinking = any(b.get("type") == "thinking" for b in content if isinstance(b, dict))
            has_text = any(b.get("type") == "text" for b in content if isinstance(b, dict))

            if has_thinking and not has_text:
                # Thinking-only entry is never the terminal state of a finished
                # turn — Claude always follows with text or a tool_use. Default
                # to "approving" rather than guessing "thinking" by recency: a
                # brief false-positive that self-corrects on the next JSONL flush
                # is strictly better than a missed approval/question. Covers both
                # tool-approval and AskUserQuestion scenarios until the tool_use
                # entry lands. Fix follows up on 4c1b66f.
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

                # Only match tool_use IDs from the most recent assistant
                # turn against subsequent tool_results — scanning all
                # 2000 tail lines would pick up stale IDs from earlier
                # turns whose results fell outside the tail window.
                # Fix for: false "approving" on long sessions.
                tool_use_ids = set()
                tool_result_ids = set()
                for prev_line in reversed(lines):
                    if not prev_line.strip():
                        continue
                    try:
                        prev = json.loads(prev_line)
                    except json.JSONDecodeError:
                        continue
                    prev_content = (prev.get("message") or {}).get("content", [])
                    if not isinstance(prev_content, list):
                        continue
                    if prev.get("type") == "assistant":
                        for b in prev_content:
                            if isinstance(b, dict) and b.get("type") == "tool_use":
                                tool_use_ids.add(b.get("id"))
                        break  # only the most recent assistant turn
                    elif prev.get("type") == "user":
                        for b in prev_content:
                            if isinstance(b, dict) and b.get("type") == "tool_result":
                                tool_result_ids.add(b.get("tool_use_id"))
                if tool_use_ids - tool_result_ids:
                    return "approving"

            # Real user message or tool_result → Claude should be responding.
            return "thinking"

        # Skip non-conversation entries (system, file-history-snapshot, etc.)
        continue

    return "unknown"


def get_pending_tool_name(lines: list[str]) -> str | None:
    """Return the name of the tool_use the session is currently blocked on, or None.

    Returns "<unknown-pending>" when stop_reason=="tool_use" on the last
    assistant entry but the tool_use block has not yet been written to JSONL.

    Used by the priority chain to distinguish a Task-subagent wait (keep
    "subagent") from a parent-side approval prompt while a child claude is
    alive (promote to "approving").
    """
    saw_local_command = False

    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg_type = obj.get("type")

        if msg_type in ("file-history-snapshot", "attachment", "custom-title",
                        "agent-name", "permission-mode"):
            continue

        if msg_type == "system" and obj.get("subtype") == "local_command":
            saw_local_command = True
            continue

        if msg_type == "assistant":
            message = obj.get("message") or {}
            if message.get("model") == "<synthetic>":
                return None

            content = message.get("content", [])
            if isinstance(content, str):
                return None

            # Assistant has real tool_use blocks — return the first non-AskUserQuestion
            # tool name (questioning is handled by the questioning branch earlier).
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    name = b.get("name")
                    if name and name != "AskUserQuestion":
                        return name

            # Thinking-only message but stop_reason=="tool_use": the tool_use
            # block hasn't been written yet. Mirrors detect_session_state L253.
            has_thinking = any(b.get("type") == "thinking" for b in content if isinstance(b, dict))
            if has_thinking and message.get("stop_reason") == "tool_use":
                return "<unknown-pending>"

            return None

        if msg_type == "user":
            message = obj.get("message") or {}
            content = message.get("content", [])
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
                continue
            if saw_local_command:
                saw_local_command = False
                continue
            if text.strip() == "[Request interrupted by user for tool use]":
                return None

            is_tool_result = isinstance(content, list) and any(
                isinstance(b, dict) and b.get("type") == "tool_result"
                for b in content
            )
            if is_tool_result:
                # Rejection: no pending approval.
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
                            return None

                # Parallel tool calls: some results missing. Find the first
                # unmatched tool_use in the most-recent assistant turn.
                tool_use_blocks: list[dict] = []
                tool_result_ids: set[str] = set()
                for prev_line in reversed(lines):
                    if not prev_line.strip():
                        continue
                    try:
                        prev = json.loads(prev_line)
                    except json.JSONDecodeError:
                        continue
                    prev_content = (prev.get("message") or {}).get("content", [])
                    if not isinstance(prev_content, list):
                        continue
                    if prev.get("type") == "assistant":
                        for b in prev_content:
                            if isinstance(b, dict) and b.get("type") == "tool_use":
                                tool_use_blocks.append(b)
                        break
                    elif prev.get("type") == "user":
                        for b in prev_content:
                            if isinstance(b, dict) and b.get("type") == "tool_result":
                                tool_result_ids.add(b.get("tool_use_id"))
                for b in tool_use_blocks:
                    if b.get("id") not in tool_result_ids:
                        name = b.get("name")
                        if name and name != "AskUserQuestion":
                            return name

            return None

        continue

    return None


def get_plan_pending_info(lines: list[str]) -> dict:
    """Return structured plan-approval-pending info.

    Shape:
        {
            "pending": bool,          # strict backend answer: True only with direct evidence
            "confidence": "observed" | "inferred-stale-plan-entry" | "not-pending",
            "evidence": {
                "last_permission_mode_entry": str | None,
                "assistant_activity_after": bool,
                "exit_plan_mode_seen": bool,
                "enter_plan_mode_after_exit": bool,
            }
        }

    `confidence == "inferred-stale-plan-entry"` marks the case where a
    `permission-mode:"plan"` entry exists but assistant activity followed
    it — classic "session resumed mid-plan, then continued" OR "user
    silently shift+tab'd back into plan mode after edits".  The JSONL
    cannot distinguish the two, so the backend reports pending=False but
    surfaces the ambiguity for the UI to decorate.  See plan file
    tender-frolicking-donut.md.
    """
    evidence = {
        "last_permission_mode_entry": None,
        "assistant_activity_after": False,
        "exit_plan_mode_seen": False,
        "enter_plan_mode_after_exit": False,
    }
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
            entry_mode = obj.get("permissionMode")
            evidence["last_permission_mode_entry"] = entry_mode
            if entry_mode == "plan":
                found_plan_mode = True
            # Any permission-mode entry (plan or otherwise) is definitive.
            break
        # Any assistant activity after the permission-mode entry means
        # the plan was already approved/completed — or the user silently
        # toggled back into plan mode after edits (unknowable).
        if msg_type == "assistant":
            model = (obj.get("message") or {}).get("model", "")
            if model == "<synthetic>":
                # Synthetic messages aren't real activity; keep scanning.
                continue
            evidence["assistant_activity_after"] = True
            # Keep scanning back to find the permission-mode entry itself
            # so we can populate last_permission_mode_entry.
            continue
        continue
    if not found_plan_mode:
        return {"pending": False, "confidence": "not-pending", "evidence": evidence}

    # Plan mode entry found.  Now check ExitPlanMode / EnterPlanMode tool calls
    # across the whole tail.  This handles the session-resume case where
    # permission-mode:"plan" is re-emitted at the top of the file.
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = obj.get("message", {})
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content", [])
        if not isinstance(content, list):
            continue
        for b in content:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                name = b.get("name")
                if name == "ExitPlanMode":
                    evidence["exit_plan_mode_seen"] = True
                elif name == "EnterPlanMode" and evidence["exit_plan_mode_seen"]:
                    # Re-entered plan mode after exiting — unambiguous pending.
                    evidence["enter_plan_mode_after_exit"] = True
        if evidence["enter_plan_mode_after_exit"]:
            break

    if evidence["enter_plan_mode_after_exit"]:
        return {"pending": True, "confidence": "observed", "evidence": evidence}
    if evidence["exit_plan_mode_seen"]:
        # Plan was explicitly exited → not pending, high confidence.
        return {"pending": False, "confidence": "not-pending", "evidence": evidence}
    if evidence["assistant_activity_after"]:
        # Assistant activity followed the plan-mode entry with no ExitPlanMode
        # recorded.  Could be (a) plan approved via edits without explicit
        # ExitPlanMode, or (b) user silently shift+tab'd back into plan.
        # Report not-pending but flag the uncertainty.
        return {"pending": False, "confidence": "inferred-stale-plan-entry", "evidence": evidence}
    # Plan mode entry with no following activity → confidently pending.
    return {"pending": True, "confidence": "observed", "evidence": evidence}


def _is_plan_approval_pending(lines: list[str]) -> bool:
    """Back-compat wrapper returning the plain bool."""
    return get_plan_pending_info(lines)["pending"]


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


def _session_has_exit_command(lines: list[str]) -> bool:
    """Check if the session ended via /exit (or /clear) after its last real turn.

    After /exit, the trailing synthetic "No response requested." is a
    session-end marker, not a session-resume indicator.  The process may
    linger (e.g. MCP server children still running), but the session is
    over — we should NOT apply the alive+idle+synthetic="approving"
    heuristic in that case.

    Scans backwards from the end, skipping metadata and synthetic
    assistant messages.  Returns True if a /exit or /clear local-command
    user entry is found before any real assistant message.
    """
    skip_types = ("system", "attachment", "file-history-snapshot",
                  "custom-title", "agent-name", "permission-mode",
                  "last-prompt")
    skip_tags = ("<local-command-caveat>", "<local-command-stdout>",
                 "<command-message>", "<command-args>",
                 "<ide_opened_file>", "<ide_action>", "<ide_closed_file>",
                 "<ide_active_file>", "<ide_selection>")
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
            # Skip synthetic wrap-ups; stop at any real assistant message.
            model = (obj.get("message") or {}).get("model", "")
            if model == "<synthetic>":
                continue
            return False
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
            stripped = text.strip()
            if ("<command-name>/exit</command-name>" in stripped
                    or "<command-name>/clear</command-name>" in stripped):
                return True
            # Skip other local-command/IDE wrapper entries; keep scanning.
            if any(stripped.startswith(tag) for tag in skip_tags):
                continue
            # Real user message (not /exit, not a wrapper) — session
            # didn't end here.
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


def get_permission_mode_info(lines: list[str]) -> dict:
    """Return structured permission-mode info.

    Shape:
        {
            "observed": str | None,    # direct read from JSONL, or None if not observable
            "inferred": str | None,    # best-guess inference (today's behavior), or None
            "confidence": "observed" | "inferred-exit-plan" | "inferred-edits-after-plan"
                          | "inferred-plan-at-tail" | "none",
            "evidence": {
                "last_permission_mode_entry": str | None,
                "lines_since_entry": int,
                "exit_plan_mode_seen_after": bool,
                "edit_tools_seen_after": bool,
                "enter_plan_mode_seen_after": bool,
            }
        }

    The backend never hides uncertainty: when the current mode must be
    inferred from post-entry evidence (the classic "permission-mode:plan"
    at line 1 + edit tools after" case), `observed` is None and the
    client decides whether to trust the inference or display "unknown".
    See plan file tender-frolicking-donut.md for rationale.
    """
    PLAN_EXIT_TOOLS = {"Write", "Edit", "Bash", "NotebookEdit", "ExitPlanMode"}
    evidence = {
        "last_permission_mode_entry": None,
        "lines_since_entry": 0,
        "exit_plan_mode_seen_after": False,
        "edit_tools_seen_after": False,
        "enter_plan_mode_seen_after": False,
    }

    # Find the most recent permission-mode entry.
    entry_idx = -1
    mode = None
    for idx in range(len(lines) - 1, -1, -1):
        line = lines[idx]
        if "permissionMode" not in line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") != "permission-mode":
            continue
        candidate = obj.get("permissionMode")
        if not candidate:
            continue
        entry_idx = idx
        mode = candidate
        evidence["last_permission_mode_entry"] = mode
        break

    if entry_idx < 0:
        return {"observed": None, "inferred": None, "confidence": "none", "evidence": evidence}

    evidence["lines_since_entry"] = len(lines) - 1 - entry_idx

    if mode != "plan":
        # Non-plan entries are treated as directly observed.  A silent
        # shift+tab after this entry is unknowable but rare enough that
        # we trust the most recent observation.  Same behavior as today.
        return {"observed": mode, "inferred": mode, "confidence": "observed", "evidence": evidence}

    # mode == "plan": scan forward for exit/edit signals.
    for later_line in lines[entry_idx + 1:]:
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
            if not isinstance(b, dict) or b.get("type") != "tool_use":
                continue
            name = b.get("name")
            if name == "ExitPlanMode":
                evidence["exit_plan_mode_seen_after"] = True
            elif name == "EnterPlanMode":
                evidence["enter_plan_mode_seen_after"] = True
            elif name in PLAN_EXIT_TOOLS:
                evidence["edit_tools_seen_after"] = True

    # No evidence at all after the plan entry → plan is at the tail, confident.
    if (not evidence["exit_plan_mode_seen_after"]
            and not evidence["edit_tools_seen_after"]
            and not evidence["enter_plan_mode_seen_after"]):
        return {"observed": "plan", "inferred": "plan",
                "confidence": "observed", "evidence": evidence}

    # Re-entry into plan mode after exiting → observed as plan.
    if evidence["enter_plan_mode_seen_after"] and evidence["exit_plan_mode_seen_after"]:
        return {"observed": "plan", "inferred": "plan",
                "confidence": "observed", "evidence": evidence}

    # ExitPlanMode was called → today's inference would say acceptEdits.
    if evidence["exit_plan_mode_seen_after"]:
        return {"observed": None, "inferred": "acceptEdits",
                "confidence": "inferred-exit-plan", "evidence": evidence}

    # Edit tools after plan entry but no explicit exit → today's inference
    # would say acceptEdits, but this is the classic silent-shift+tab bug.
    if evidence["edit_tools_seen_after"]:
        return {"observed": None, "inferred": "acceptEdits",
                "confidence": "inferred-edits-after-plan", "evidence": evidence}

    # Fallback (shouldn't reach here given the branches above).
    return {"observed": "plan", "inferred": "plan",
            "confidence": "inferred-plan-at-tail", "evidence": evidence}


def get_permission_mode(lines: list[str]) -> str | None:
    """Back-compat wrapper returning the best-guess string.

    Prefer `get_permission_mode_info` for new code — it carries the
    confidence signal needed to honestly represent silent shift+tab
    scenarios.
    """
    info = get_permission_mode_info(lines)
    return info["observed"] or info["inferred"]


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


def focus_warp_tab(session_name: str, cwd: str = "", session_id: str = "",
                   cwd_live_siblings: int = 0) -> dict:
    """Focus the Warp tab whose title matches one of our candidate terms.

    Warp has no AppleScript dictionary, its URI scheme can't focus existing
    tabs (warpdotdev/warp#8611), and its accessibility tree doesn't expose
    tabs. The only reliable way to enumerate every tab across every window
    is to raise each window and cycle its tabs via Cmd+Shift+], reading
    `name of window 1` after each keystroke. This is slow but exhaustive.

    We match on stripped-glyph comparisons against an ordered candidate
    list. STRONG candidates (session_id, session_name) uniquely identify
    the target session — we cycle exhaustively to find them and never
    short-circuit on a weak match. WEAK candidates (cwd-derived) are only
    accepted on a second pass after all strong candidates fail.

    Match is exact-or-truncation-suffix: Warp truncates long titles with a
    leading ".." prefix (e.g. "..ects/claude-dashboard" for the full
    "personal-projects/claude-dashboard").
    """
    # Build ordered match candidates, most-specific first.
    candidates: list[str] = []
    if session_id:
        candidates.append(f"claude:{session_id}")
    if session_name:
        candidates.append(session_name)
    cwd_stripped = cwd.rstrip("/") if cwd else ""
    cwd_base = os.path.basename(cwd_stripped) if cwd_stripped else ""
    cwd_parent_base = os.path.basename(os.path.dirname(cwd_stripped)) if cwd_stripped else ""
    cwd_parent_slash_base = f"{cwd_parent_base}/{cwd_base}" if cwd_parent_base and cwd_base else ""
    cwd_derived = [c for c in (cwd_parent_slash_base, cwd_base) if c]
    cwd_candidate_indices: set[int] = set()
    for c in cwd_derived:
        if c and c not in candidates:
            candidates.append(c)
            cwd_candidate_indices.add(len(candidates) - 1)
    if not candidates:
        candidates.append("Claude Code")

    def ascii_escape(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')

    escaped_candidates = [ascii_escape(c) for c in candidates]
    as_list = "{" + ", ".join(f'"{c}"' for c in escaped_candidates) + "}"
    weak_indices_as = "{" + ", ".join(str(i + 1) for i in sorted(cwd_candidate_indices)) + "}"
    if not cwd_candidate_indices:
        weak_indices_as = "{}"
    has_weak_as = "true" if cwd_candidate_indices else "false"

    # AppleScript strategy:
    #   Phase 1 (strong): for every Warp window, raise it, then cycle tabs
    #     via Cmd+Shift+] reading `name of window 1` between keystrokes.
    #     Use a visit count (tab count or 20, whichever is smaller) bounded
    #     by detecting when we loop back to the starting title. Check each
    #     visited tab's stripped name against every STRONG candidate. Stop
    #     on first match.
    #   Phase 2 (weak): repeat the cycle, matching WEAK (cwd) candidates.
    #   Phase 3 (fail): restore the originally focused window/tab by
    #     raising it (we can't restore the exact tab — keystroke cost).
    apple_script = f'''
        on stripGlyph(s)
            if s is missing value then return ""
            try
                set n to count of s
            on error
                return ""
            end try
            if n < 3 then return s as text
            if (character 2 of s) is " " then
                set firstChar to character 1 of s
                if (id of firstChar) > 127 then
                    return text 3 thru -1 of s
                end if
            end if
            return s as text
        end stripGlyph

        on endsWith(haystack, suffix)
            if suffix is "" then return false
            set sLen to count of suffix
            set hLen to count of haystack
            if sLen > hLen then return false
            return (text (hLen - sLen + 1) thru hLen of haystack) is equal to suffix
        end endsWith

        on matchOne(targetStripped, cand)
            set candText to cand as text
            if targetStripped is equal to candText then return true
            set tLen to count of targetStripped
            if tLen ≥ 6 and (text 1 thru 2 of targetStripped) is ".." then
                set truncatedSuffix to text 3 thru -1 of targetStripped
                if my endsWith(candText, truncatedSuffix) then return true
            end if
            return false
        end matchOne

        -- Try every candidate against one tab title. Returns matched
        -- 1-based candidate index, or 0 if no match. `allowWeak` controls
        -- whether weak (cwd) candidates are eligible — Phase 1 passes
        -- false, Phase 2 passes true.
        on matchAllCands(targetStripped, cands, weakIndices, allowWeak)
            set candCount to count of cands
            repeat with ci from 1 to candCount
                set isWeak to false
                repeat with wk in weakIndices
                    if (wk as integer) is equal to ci then
                        set isWeak to true
                        exit repeat
                    end if
                end repeat
                if isWeak and not allowWeak then
                    -- skip weak in strong pass
                else
                    if my matchOne(targetStripped, item ci of cands) then
                        return ci
                    end if
                end if
            end repeat
            return 0
        end matchAllCands

        -- Poll `name of window 1` until its stripped title differs from
        -- `previous`, up to maxMs. The tab-switch keystroke and AXRaise
        -- return before Warp has updated the window title, so a fixed
        -- delay either reads a stale title (missed match, or a spurious
        -- equality with the anchor that exits the cycle after one tab)
        -- or is pessimistically slow. Adaptive polling fixes the race
        -- without adding latency when the system is responsive. On
        -- timeout we return the last stripped read — same fallback as
        -- the previous fixed-delay code. IMPORTANT: AppleScript handlers
        -- do NOT inherit the caller's `tell` target. Without the explicit
        -- `tell application "System Events" ...` below, `name of window 1`
        -- addresses nothing and returns "" every poll, causing the gate
        -- to time out on every iteration (300ms × 40+ steps = several
        -- seconds of false "not found"). Found via live debugging.
        on waitForTitleChange(previous, maxMs)
            set pollMs to 15
            set maxIters to maxMs div pollMs
            if maxIters < 1 then set maxIters to 1
            set curStripped to previous
            repeat with i from 1 to maxIters
                set curRaw to ""
                try
                    tell application "System Events" to tell process "Warp" to set curRaw to name of window 1
                end try
                set curStripped to my stripGlyph(curRaw)
                if curStripped is not equal to previous then return curStripped
                delay 0.015
            end repeat
            return curStripped
        end waitForTitleChange

        set cands to {as_list}
        set weakIndices to {weak_indices_as}
        set hasWeak to {has_weak_as}
        if hasWeak then
            set phaseCount to 2
        else
            -- No cwd-derived candidates → phase 2 would be identical to
            -- phase 1 and purely wasted work. Skip it.
            set phaseCount to 1
        end if

        tell application "Warp" to activate
        delay 0.05
        tell application "System Events"
            tell process "Warp"
                set winList to every window
                set winCount to count of winList
                if winCount is 0 then return "no_windows"

                -- Two phases: phase 1 checks STRONG candidates (session_id,
                -- session_name) only; phase 2 accepts WEAK (cwd) candidates.
                -- Never short-circuit on a weak match while a strong one
                -- might still be hiding in an unvisited tab.
                repeat with phase from 1 to phaseCount
                    set allowWeak to (phase is 2)
                    set beforeRaise to ""
                    repeat with wi from 1 to winCount
                        set w to item wi of winList
                        try
                            perform action "AXRaise" of w
                        end try

                        -- Wait for the window title to reflect the newly-raised
                        -- window (up to 120ms). On the first iteration
                        -- beforeRaise is "" so the helper returns as soon as a
                        -- non-empty title appears, or times out if the raise
                        -- didn't change anything.
                        set anchorStripped to my waitForTitleChange(beforeRaise, 120)

                        set hit to my matchAllCands(anchorStripped, cands, weakIndices, allowWeak)
                        if hit > 0 then
                            return "found:" & (hit - 1) & ":" & anchorStripped
                        end if

                        -- Cycle forward up to 20 tabs, stopping when we loop
                        -- back to the anchor title (or hit the cap). 20 is a
                        -- safety cap — Warp tab strips typically hold ≤12.
                        -- `prev` tracks the previously-visited tab's title so
                        -- the gate works on every step — comparing only
                        -- against anchorStripped would let stale reads from
                        -- tabs two steps back return instantly and defeat the
                        -- race protection.
                        set prev to anchorStripped
                        repeat with step from 1 to 20
                            key code 30 using {{command down, shift down}}
                            set curStripped to my waitForTitleChange(prev, 120)
                            if curStripped is equal to anchorStripped then
                                exit repeat
                            end if
                            set hit to my matchAllCands(curStripped, cands, weakIndices, allowWeak)
                            if hit > 0 then
                                return "found:" & (hit - 1) & ":" & curStripped
                            end if
                            set prev to curStripped
                        end repeat

                        -- Seed the next window's gate with the actual last
                        -- title we saw (prev), not anchorStripped — on
                        -- wrap-around they're equal, but on the 20-cap path
                        -- they aren't, and anchorStripped would make the
                        -- next waitForTitleChange return immediately.
                        set beforeRaise to prev
                    end repeat
                end repeat

                return "not_found"
            end tell
        end tell
    '''
    try:
        result = subprocess.run(
            ["osascript", "-e", apple_script],
            capture_output=True, text=True, timeout=20,
        )
        output = result.stdout.strip()
        if output.startswith("found:"):
            # Payload shape: "found:<idx>:<tab_name>" where idx is the 0-based
            # position of the matched candidate in our list. Tab names can
            # contain colons, so split only on the first two.
            rest = output[len("found:"):]
            idx_str, _, tab_name = rest.partition(":")
            try:
                matched_idx = int(idx_str)
            except ValueError:
                matched_idx = -1
            resp = {"ok": True, "action": "focused", "detail": f"Focused tab: {tab_name}"}
            # Warn when we fell through to a cwd-derived candidate and
            # another live session shares this cwd — the match is not
            # guaranteed to be the right tab. UI surfaces this as a toast
            # pointing at the SessionStart hook install docs.
            if matched_idx in cwd_candidate_indices and cwd_live_siblings > 0:
                resp["warning"] = "ambiguous_cwd"
                resp["detail"] = (
                    f"Focused a tab in '{cwd_base}', but {cwd_live_siblings + 1} live "
                    "sessions share this cwd. Install the SessionStart hook "
                    "(see README → Warp Tab Focus Notes) to disambiguate."
                )
            return resp
        if output == "no_windows":
            return {"ok": False, "action": "not_found", "detail": "No Warp windows open"}
        shown = candidates[0] if candidates else ""
        return {"ok": False, "action": "not_found",
                "detail": f"No Warp tab matching '{shown}'"}
    except Exception as e:
        return {"ok": False, "action": "error", "detail": str(e)}


def open_session(session_id: str, config_dir: str, pid: int | None, alive: bool,
                 session_name: str = "", cwd: str = "",
                 cwd_live_siblings: int = 0) -> dict:
    """Open / focus a session.  Returns {ok, action, detail}."""
    if alive and pid:
        app = find_parent_app(pid)
        if app == "Warp":
            return focus_warp_tab(session_name, cwd=cwd, session_id=session_id,
                                  cwd_live_siblings=cwd_live_siblings)
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


def _activity_ts(session: dict) -> float:
    last_activity = session.get("last_activity")
    if not last_activity:
        return 0.0
    try:
        return datetime.fromisoformat(last_activity.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _hide_shadow_plans(sessions: list[dict]) -> None:
    # When the user runs Claude multiple times in the same cwd, each JSONL
    # becomes its own session card and may reference a plan file. Plans
    # live in a shared ~/.claude/plans/ dir and represent "the current plan
    # for this cwd", not per-session archives. Without this step, every
    # sibling card shows its own plan and the user cannot tell which one
    # is current. Policy: keep plan_file_path only on the session with the
    # greatest last_activity within each non-empty cwd group; null it on
    # older ones. Fix for: shadow-session plan confusion (2026-04-15).
    groups: dict[str, list[dict]] = {}
    for s in sessions:
        if not (s.get("cwd") or "") or not s.get("plan_file_path"):
            continue
        groups.setdefault(s["cwd"], []).append(s)
    for group in groups.values():
        if len(group) < 2:
            continue
        group.sort(key=_activity_ts, reverse=True)
        for stale in group[1:]:
            stale["plan_file_path"] = None
            stale["plan_file_exists"] = False


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
                    permission_mode_info = get_permission_mode_info(lines)
                    permission_mode = permission_mode_info["observed"] or permission_mode_info["inferred"]
                    plan_pending_info = get_plan_pending_info(lines)
                    plan_file_path = extract_plan_file_path(lines)
                    plan_file_exists = bool(plan_file_path) and os.path.isfile(plan_file_path)
                    topic = get_session_topic(jsonl_file)
                    last_user_msg = extract_last_user_message(lines)
                    last_assistant_text = extract_last_assistant_text(lines)
                    model_info = extract_last_assistant_model_and_thinking(lines)
                    session_state = detect_session_state(lines)

                    pid_info = pid_map.get(session_id, {})
                    pid = pid_info.get("pid")
                    # Prefer the live process cwd (always current). Fall back to the
                    # cwd recorded in the JSONL — the folder name under
                    # ~/.claude/projects/ encodes "/" as "-" with no escape for real
                    # "-" chars, so decoding it is lossy. The JSONL field is ground
                    # truth and works for dead sessions too.
                    cwd = pid_info.get("cwd", "") or (extract_cwd(lines) or "")
                    kind = pid_info.get("kind", "")
                    session_name = pid_info.get("name", "") or get_session_title(lines) or ""
                    alive = is_pid_alive(pid) if pid else False

                    # Also check if the PID (or its parent) is among running claude procs
                    if not alive and pid:
                        alive = pid in all_claude_pids

                    if alive:
                        activity = detect_activity_state(pid) if pid else "idle"
                        if activity == "subagent":
                            # Strict mode: parent can be blocked on a tool-approval prompt
                            # while a child claude (Task subagent, or a lingering child) is
                            # still alive. Before this gate, the subagent branch short-
                            # circuited and hid the approval prompt — user would miss it.
                            # Distinguish by the pending tool:
                            #   - "Task": legitimate subagent wait -> "subagent".
                            #   - any other tool: parent blocked on approval -> "approving".
                            #   - "<unknown-pending>" + stale JSONL: stop_reason=="tool_use"
                            #     but the block isn't in JSONL yet -> "approving".
                            # Questioning is checked first so AskUserQuestion still wins
                            # during an active subagent.
                            # Fix for: strict-mode subagent-hides-approving (2026-04-15).
                            pending_tool = get_pending_tool_name(lines)
                            if session_state == "questioning":
                                status = "questioning"
                            elif pending_tool and pending_tool not in ("Task", "<unknown-pending>"):
                                status = "approving"
                            elif pending_tool == "<unknown-pending>" and (time.time() - file_mtime) > 3:
                                status = "approving"
                            else:
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
                            # Promote to "thinking" whenever the process tree has a
                            # meaningful descendant, even if session_state=="waiting".
                            # Claude Code does not always flush the new user entry to
                            # JSONL before tool execution begins — when it doesn't, the
                            # JSONL still shows the previous turn's end_turn (so
                            # session_state=="waiting") while a Bash/Edit/etc. child is
                            # already running for the new turn. Without this, the
                            # dashboard would show "waiting" while Claude is actively
                            # working.
                            #
                            # Trade-off (2026-04-16, deliberate): this re-introduces the
                            # lingering-bg-server false "thinking" that the 2026-04-15
                            # fix tried to suppress. If a user ran `npm run dev`/vite/
                            # serve in a prior turn and left it running, that descendant
                            # will keep the session showing "thinking" indefinitely. The
                            # user accepted this trade-off because missing a real
                            # in-flight turn (where Claude is actually working) is the
                            # worse failure mode — the bg-server false positive is
                            # cosmetic, the missed-thinking false negative causes the
                            # user to ignore an active session.
                            if session_state == "thinking" and activity == "idle":
                                # During LLM inference the node process appears idle
                                # (waiting on API HTTP response, no child processes,
                                # low CPU).  Use JSONL recency to distinguish "still
                                # processing" from "finished but waiting for input".
                                # If the file was written recently (<3s), Claude is
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
                                if jsonl_age > 3 and not last_is_user:
                                    # Claude was mid-turn but hasn't written anything
                                    # in >3s while the process is idle — most likely
                                    # blocked on a permission prompt (the pending
                                    # tool_use hasn't been written to JSONL yet).
                                    # If Claude had finished, there'd be a real
                                    # assistant entry making session_state "waiting".
                                    # Reduced from 10s: the stop_reason=="tool_use" check
                                    # in detect_session_state handles most cases; this is
                                    # a last-resort fallback for edge cases where the
                                    # thinking entry's stop_reason wasn't yet available.
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
                            #
                            # We intentionally do NOT promote "waiting" to
                            # "thinking" based on main-process CPU alone:
                            # interactive claude --chrome sessions routinely
                            # burn ~14% CPU at idle (terminal rendering + chrome
                            # extension IPC), so CPU delta is not a reliable
                            # mid-inference signal. JSONL is authoritative; a
                            # few seconds of lag between user-submits-prompt
                            # and JSONL-gets-the-user-entry is acceptable.
                            # Fix for: false "thinking" on idle chrome sessions (2026-04-15).
                            if (activity == "idle" and _last_entry_is_synthetic(lines)
                                    and not _session_has_exit_command(lines)):
                                # Alive process with idle activity and a synthetic last
                                # entry means session was resumed and is now blocked on
                                # approval. The _synthetic_follows_rejection guard from
                                # fcedcc5 is unnecessary here: after a rejection, Claude
                                # actively processes the response (activity="thinking"),
                                # and by the time it settles to idle the JSONL has new
                                # entries making the synthetic no longer the last entry.
                                #
                                # The /exit guard handles sessions that ended cleanly but
                                # whose process lingers (e.g. MCP server children still
                                # running).  Without it, exited sessions falsely report
                                # "approving" because the synthetic session-end marker
                                # looks like a session-resume wrap-up.
                                status = "approving"
                            else:
                                status = "waiting"
                        # Plan-pending semantics are resolved client-side now.
                        # The client reads plan_pending_info and, in strict
                        # mode, surfaces ambiguous cases as "unknown"; in
                        # lenient mode it decorates the base status. Promoting
                        # to "questioning" here caused false-questioning while
                        # Claude was mid-turn after a resumed permission-mode
                        # entry — the JSONL shape cannot distinguish "plan
                        # interview idle" from "alive, assistant entries not
                        # yet flushed". "questioning" stays reserved for
                        # AskUserQuestion, detected earlier in the chain.
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
                        # Prefer an authoritative cwd — decoding the project folder
                        # name is lossy (dash/slash ambiguity).
                        "project": abbreviate_home(cwd) if cwd else friendly_project_name(project_dir),
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
                        "model": model_info["model"],
                        "thinking_recent": model_info["thinking_recent"],
                        "permission_mode": permission_mode,
                        "permission_mode_info": permission_mode_info,
                        "plan_pending_info": plan_pending_info,
                        "kind": kind,
                        "todos": todos,
                        "file_size_kb": round(file_size / 1024, 1),
                        "jsonl_path": jsonl_file,
                        "plan_file_path": plan_file_path,
                        "plan_file_exists": plan_file_exists,
                        "user_notes": ann.get("notes", ""),
                        "user_todos": ann.get("todos", []),
                    })

        sessions = [s for s in sessions if s["status"] not in ("inactive", "unknown")]

        # Count live-session siblings per cwd. Two sessions in the same cwd
        # land in indistinguishable Warp tabs (default title = cwd basename),
        # so focus can't tell them apart without the SessionStart hook.
        live_cwd_counts: dict[str, int] = {}
        for s in sessions:
            if s.get("alive") and s.get("cwd"):
                live_cwd_counts[s["cwd"]] = live_cwd_counts.get(s["cwd"], 0) + 1
        for s in sessions:
            if s.get("alive") and s.get("cwd"):
                s["cwd_live_siblings"] = live_cwd_counts[s["cwd"]] - 1
            else:
                s["cwd_live_siblings"] = 0

        # Tier 0: all active statuses — equal priority so status changes
        # within active sessions don't cause cards to swap positions.
        # Tier 1/2: dead sessions by recency.
        status_order = {
            "questioning": 0,
            "approving": 0,
            "waiting": 0,
            "thinking": 0,
            "subagent": 0,
            "hook": 0,
            "recent": 1,
            "idle": 2,
        }
        sessions.sort(key=lambda s: (
            status_order.get(s["status"], 5),
            -(datetime.fromisoformat(s["last_activity"].replace("Z", "+00:00")).timestamp()
              if s["last_activity"] else 0),
        ))

        _hide_shadow_plans(sessions)

        accounts.append({
            "email": email,
            "config_dir": config_dir,
            "sessions": sessions,
            "rate_limits": get_rate_limits(config_dir),
        })

    return {
        "accounts": accounts,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# HTTP Server
# ---------------------------------------------------------------------------


_PLAN_DIR_ALLOWLIST = tuple(
    os.path.realpath(os.path.join(d, "plans")) + os.sep for d in CONFIG_DIRS
)


def _find_session_in_cache(session_id: str) -> dict | None:
    data = _get_cache()
    for acct in data.get("accounts", []):
        for s in acct.get("sessions", []):
            if s.get("session_id") == session_id:
                return s
    return None


def _read_plan_for_session(session_id: str) -> tuple[int, dict]:
    session = _find_session_in_cache(session_id)
    if not session:
        return 404, {"error": "session not found"}
    plan_path = session.get("plan_file_path")
    if not plan_path:
        return 404, {"error": "no plan for session"}
    # Path-traversal guard: resolve and require the file to live under
    # one of the configured ~/.claude*/plans/ directories.
    real = os.path.realpath(plan_path)
    if not any(real.startswith(prefix) for prefix in _PLAN_DIR_ALLOWLIST):
        return 403, {"error": "plan path outside allowed directories"}
    if not os.path.isfile(real):
        return 200, {"path": plan_path, "exists": False, "content": ""}
    try:
        with open(real, encoding="utf-8") as f:
            content = f.read()
    except OSError as e:
        return 500, {"error": str(e)}
    return 200, {"path": plan_path, "exists": True, "content": content}


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

        elif parsed.path.startswith("/api/plan/"):
            session_id = parsed.path.split("/api/plan/", 1)[1]
            self._json_response(*_read_plan_for_session(session_id))

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
                cwd=target.get("cwd", ""),
                cwd_live_siblings=target.get("cwd_live_siblings", 0),
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
            # Send current data immediately so new clients don't wait
            # up to 30s for the first update or keepalive timeout.
            with _cache_condition:
                current_version = _cache_version
                data = _session_cache
            if current_version > 0 and data:
                last_version = current_version
                payload = json.dumps(data)
                self.wfile.write(f"event: sessions\ndata: {payload}\n\n".encode())
                self.wfile.flush()

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
