# Test Case Catalog

This document catalogs all test scenarios for the Claude Sessions Dashboard. These tests cover backend session detection, SSE streaming, frontend integration, mobile responsiveness, and edge cases.

## Backend — Session Detection

| # | Test Case | Input/Setup | Expected Result |
|---|-----------|-------------|-----------------|
| 1 | **Active session detection** | Running Claude process with PID in sessions index | Status = alive, correct PID |
| 2 | **Dead session detection** | Stale PID in sessions index, process not running | Status = not alive, `is_pid_alive` = false |
| 3 | **PID reuse guard** | PID exists but belongs to non-Claude process | `is_pid_alive` returns false |
| 4 | **Multiple config dirs** | Sessions in both `~/.claude` and `~/.claude-personal` | Both accounts appear with correct emails |

## Backend — Session State Detection (`detect_session_state`)

| # | Test Case | JSONL tail content | Expected State |
|---|-----------|-------------------|----------------|
| 5 | **User message last** | Last entry: `{"type":"user", "message":{"content":[{"type":"text","text":"fix the bug"}]}}` | `"thinking"` |
| 6 | **Assistant text last** | Last entry: `{"type":"assistant", "message":{"content":[{"type":"text","text":"Done!"}]}}` (age > 2s) | `"waiting"` |
| 7 | **Assistant tool_use last** | Last entry: `{"type":"assistant", "message":{"content":[{"type":"tool_use","name":"Bash",...}]}}` | `"approving"` |
| 8 | **IDE event skipping** | Last entries: IDE `<ide_opened_file>` event, then assistant text before it | `"waiting"` (skips IDE event) |
| 9 | **Recent assistant message** | Last entry: assistant text, timestamp < 2s ago | `"thinking"` (still streaming) |
| 10 | **Empty transcript** | No valid JSONL entries | `"unknown"` |

## Backend — Activity Detection (`detect_activity_state`)

| # | Test Case | Process tree | Expected Activity |
|---|-----------|-------------|-------------------|
| 11 | **Subagent running** | Child process command contains "claude" | `"subagent"` |
| 12 | **Hook running** | Child process command contains "biome" or "eslint" | `"hook"` |
| 13 | **Tool execution** | Child process running bash/node (not noise) | `"thinking"` |
| 14 | **MCP server filtered** | Only child processes are MCP servers | Not counted as meaningful; falls through to CPU check |
| 15 | **Noise filtered** | Only `caffeinate`/`sleep` children | Filtered out; falls through to CPU check |
| 16 | **Idle (no descendants)** | No child processes, main CPU < 5% | `"idle"` |
| 17 | **High CPU thinking** | No child processes, main CPU > 5% | `"thinking"` |

## Backend — Data Extraction

| # | Test Case | Input | Expected |
|---|-----------|-------|----------|
| 18 | **Extract last todo** | JSONL with TodoWrite tool_use block | Returns todos array |
| 19 | **Extract session topic** | JSONL with first user message "Deploy the app" | Returns "Deploy the app" |
| 20 | **Extract last user message** | Multiple user messages in tail | Returns last one (max 200 chars) |
| 21 | **Git branch extraction** | JSONL entry with `"gitBranch": "feat/sse"` | Returns "feat/sse" |
| 22 | **Old session filtering** | JSONL file mtime > 7 days ago | Session excluded from results |

## Backend — SSE

| # | Test Case | Setup | Expected |
|---|-----------|-------|----------|
| 23 | **SSE initial data** | Connect to `/api/events` | Receives `event: sessions` within 1s |
| 24 | **SSE file-triggered push** | Modify a JSONL file while connected | New event within ~1.5s (500ms debounce + processing) |
| 25 | **SSE periodic push** | Wait with no file changes | Event every ~5s (PID check timer) |
| 26 | **SSE keepalive** | Long idle connection | `:keepalive` comment sent every ~30s |
| 27 | **SSE multiple clients** | 3 concurrent EventSource connections | All receive same events |
| 28 | **SSE client disconnect** | Close one of multiple connections | Other clients unaffected, no server error |
| 29 | **Watchdog fallback** | `watchdog` not installed | Periodic-only mode (5s), no crash |

## Frontend — SSE Integration

| # | Test Case | Setup | Expected |
|---|-----------|-------|----------|
| 30 | **Connection established** | Open dashboard | Header shows green dot + "Live" |
| 31 | **Connection lost** | Stop backend | Header shows red dot + "Disconnected", auto-retry |
| 32 | **Reconnection** | Restart backend after disconnect | Header returns to green, data resumes |
| 33 | **Edit preservation** | User editing notes when SSE update arrives | Local edits preserved, not overwritten |

## Frontend — Mobile Responsiveness

| # | Test Case | Viewport | Expected |
|---|-----------|----------|----------|
| 34 | **iPhone SE (375px)** | 375×667 | Cards in single column, no horizontal scroll |
| 35 | **iPhone 14 Pro (393px)** | 393×852 | Same as above |
| 36 | **iPad (768px)** | 768×1024 | Single column (< 920px for 2 cols) |
| 37 | **Desktop (1440px)** | 1440×900 | Multi-column grid |
| 38 | **Touch targets** | Mobile viewport | All buttons >= 44px tap area |

## Integration — End to End

| # | Test Case | Steps | Expected |
|---|-----------|-------|----------|
| 39 | **Full lifecycle** | Start backend → open browser → start a Claude session → watch dashboard | Session appears, status updates in real-time |
| 40 | **Annotations persist** | Add note + todo → restart backend | Notes and todos preserved |
| 41 | **launchd auto-restart** | `kill` the dashboard process | Process restarts within seconds |
| 42 | **Tailscale access** | Access from phone via Tailscale IP | Dashboard loads, sessions visible |

## Edge Cases

| # | Test Case | Setup | Expected |
|---|-----------|-------|----------|
| 43 | **Agent teams** | Session with multiple subagent child processes | Status shows "subagent", descendant tree captured |
| 44 | **VS Code IDE messages** | JSONL contains `<ide_opened_file>` user messages | IDE events skipped in state detection |
| 45 | **Large JSONL file** | Session file > 10MB | `tail_lines` only reads last N lines, no memory issue |
| 46 | **Concurrent annotations** | Two browser tabs save annotations simultaneously | Last write wins, no corruption (atomic replace) |
| 47 | **No config dirs exist** | `CLAUDE_CONFIGS` points to nonexistent paths | Empty dashboard, no crash |

## Running Tests

Currently these are manual test scenarios. To verify:

### Quick Smoke Test

```bash
# Backend serves
curl -s http://localhost:8484/api/sessions | python3 -m json.tool | head

# SSE streams
curl -N http://localhost:8484/api/events
# Should show event: sessions data within 1 second

# File-triggered update
touch ~/.claude/projects/*/$(ls ~/.claude/projects/*/  | head -1)
# SSE should push a new event within ~1.5 seconds

# launchd auto-restart
kill $(launchctl list | grep claude-dashboard | awk '{print $1}')
sleep 8
curl http://localhost:8484/  # Should return 200
```

### Mobile Test

Open Chrome DevTools → Device Toolbar → select iPhone SE (375px). Verify:
- Cards stack in single column
- No horizontal scrollbar
- Status badges visible
- Touch targets (buttons) are at least 44px tall
