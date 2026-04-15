"""PID liveness and process-tree activity probes (subprocess wrappers).

Owns: nothing.
Depends on: stdlib (os, subprocess) only.
"""

import os
import subprocess


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
        cmd = d["command"]
        # Subagent: another claude process spawned as child. Match only when
        # "claude" is the actual executable (first token's basename), not any
        # substring — otherwise the zsh Bash-tool wrapper sources shell
        # snapshots from ~/.claude/shell-snapshots/..., and the "claude" in
        # the path falsely flagged every Bash tool call as a subagent.
        first_token = cmd.split()[0] if cmd.split() else ""
        exe = first_token.rsplit("/", 1)[-1].lower()
        if exe == "claude":
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

    # No meaningful descendants — check main process CPU.
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
