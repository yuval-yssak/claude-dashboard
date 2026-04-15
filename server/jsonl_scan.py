"""Pure JSONL parsing helpers: tail-read + per-message extractors.

Owns: nothing.
Depends on: config (TODO_SCAN_LINES); stdlib json only.

Status detection (status_detect.py) builds on top of these primitives — keep
this module free of state-detection logic so the two layers stay decoupled.
"""

import json

from config import TODO_SCAN_LINES


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


def get_session_title(lines: list[str]) -> str | None:
    """Extract session title from JSONL: prefer custom-title over ai-title."""
    for line in reversed(lines):
        if "custom-title" not in line and "ai-title" not in line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg_type = obj.get("type")
        if msg_type == "custom-title":
            return obj.get("customTitle")
        if msg_type == "ai-title":
            return obj.get("aiTitle")
    return None


def extract_plan_file_path(lines: list[str]) -> str | None:
    # Plan files are referenced via attachment entries with
    # type="plan_mode" and a planFilePath field. Scan tail in reverse
    # to find the most recent one for the session.
    for line in reversed(lines):
        if '"plan_mode"' not in line or "planFilePath" not in line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        attachment = obj.get("attachment") or {}
        if attachment.get("type") != "plan_mode":
            continue
        path = attachment.get("planFilePath")
        if isinstance(path, str) and path:
            return path
    return None
