# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A real-time multi-account Claude Code session monitor. Python HTTP backend watches JSONL files and process trees, pushes updates via SSE to a React frontend that displays session cards grouped by account.

## Commands

```bash
# Backend
python3 server/claude_dashboard.py              # Starts on :8484

# Frontend
cd client && npm install                         # Install deps
cd client && npm run dev                         # Dev server on :5173 (proxies /api to :8484)
cd client && npm run build                       # Production build → client/dist/
cd client && npm run lint                        # Biome linter
cd client && npm run format                      # Biome formatter

# Python linting
ruff check server/                               # Uses server/ruff.toml

# Deploy as macOS launchd service
./deploy/install.sh

# HTTPS via Tailscale (required for PWA install on mobile)
tailscale serve --bg --https=443 http://localhost:8484
```

No automated test suite — manual test scenarios are in `docs/TESTING.md`.

**Browser verification: always use http://localhost:8484, not :5173.** The user runs the dashboard in production-style mode against the Python backend, which serves the built SPA at `/`. After making frontend changes you want the user to verify, run `cd client && npm run build` so the change is reflected at :8484. The Vite dev server at :5173 is only relevant if `npm run dev` is actively running, which is not the default workflow.

## Architecture

```
Browser (React 19 + TypeScript)
  ↕ REST + SSE
Python 3 HTTP Server (stdlib http.server + threading)
  ↕ watchdog (FSEvents) + ps/pgrep
~/.claude/ and ~/.claude-personal/ JSONL files + process tree
```

**Backend** (`server/`, Python 3.10+ stdlib):

The orchestrator lives in `claude_dashboard.py`; pure utilities were extracted into sibling modules. Prefer editing a utility module over growing the orchestrator.

| File | Responsibility | Edit here when… |
|------|----------------|-----------------|
| `claude_dashboard.py` | HTTP/SSE server, session collection, **state detection chain**, watchdog loop (500ms debounce + 5s periodic), AppleScript session resume, version-tracked SSE cache | Touching status logic, request handlers, the refresh loop, or SSE broadcasting |
| `jsonl_scan.py` | Pure JSONL tail parsing — last user/assistant message, TodoWrite todos, current activity, session title, git branch, plan file path, timestamps (scans last 2000 lines) | Adding or changing what gets extracted from JSONL files |
| `process_monitor.py` | Process tree probing — `is_pid_alive`, `get_descendant_processes`, `detect_activity_state` (CPU + command), `find_all_claude_pids` | Changing how process liveness or activity is detected |
| `query_helpers.py` | On-disk read helpers — `read_json`, `get_rate_limits`, `get_account_email` | Reading other files out of `~/.claude*` |
| `annotations.py` | Notes/todos persistence to `claude-dashboard-data.json` with thread lock + atomic replace | Touching annotation storage |
| `config.py` | Constants — `PORT`, `CONFIG_DIRS`, `ANNOTATIONS_FILE`, debounce/interval/threshold values | Adding a tunable |
| `utils.py` | Pure formatters — `friendly_project_name`, `time_ago` | Pure display-string helpers |

**Important:** status detection (the "whack-a-mole" area flagged below) lives in `claude_dashboard.py`, not `jsonl_scan.py`. `jsonl_scan.py` only extracts raw data from JSONL; `claude_dashboard.py` interprets it into states like `approving`, `thinking`, `waiting`.

**Frontend** (`client/src/`):
- `App.tsx` — SSE connection, global state
- `components/` — Header, AccountSection (drag-drop grid), SessionCard, AnnotationsPanel, ClaudeTodos, StatusBadge, SummaryBar, Toast
- `hooks/` — useSSE (EventSource), useDebouncedSave, useCardOrdering (drag-drop + pinning via @dnd-kit)
- Mobile-responsive (single column < 500px)
- PWA-installable (manifest + no-op service worker, no offline support — app requires live SSE connection)

## Session State Detection

State priority (sort tiers): `active (questioning/approving/waiting/thinking/subagent/hook) > recent > idle > inactive`

The backend combines JSONL analysis (conversational state) with process tree inspection (activity detection). IDE events from VS Code are filtered out. Messages < 2s old are treated as still streaming.

### Session Sort Order

Sessions are sorted by backend status tier (primary) and `last_activity` descending (secondary):

| Tier | Status | Meaning |
|------|--------|---------|
| 0 | `questioning`, `approving`, `waiting`, `thinking`, `subagent`, `hook` | Active sessions — equal priority, sorted by last activity |
| 1 | `recent` | Dead process, last activity < 5 min ago |
| 2 | `idle` | Dead process, last activity 5 min – 2 hours ago |
| — | `inactive`, `unknown` | Filtered out; not displayed |

Within the same tier, sessions are sorted by `last_activity` timestamp (newest first). Status changes within a tier do not cause cards to swap positions — only tier transitions trigger reordering.

### Pinned Sessions

Sessions pinned via the UI always appear at the top of their account group. Pinning is protected during server reorders — a pinned session cannot be displaced by other sessions being moved.

## API Endpoints

- `GET /api/sessions` — full session data
- `GET /api/events` — SSE stream
- `GET /api/annotations/<id>` — fetch notes/todos
- `PUT /api/annotations/<id>` — save notes/todos
- `POST /api/open/<id>` — resume session (AppleScript)
- `GET /` — serves React SPA

## Environment Variables

- `CLAUDE_DASHBOARD_PORT` (default: `8484`)
- `CLAUDE_CONFIGS` (default: `~/.claude,~/.claude-personal`) — config directories to watch

## Key Thresholds

- JSONL tail scan: 2000 lines
- File change debounce: 500ms
- Periodic refresh: 5s
- Session age filter: 7 days
- Idle threshold: 2 hours without activity
- High CPU indicator: > 5.0%
- Streaming recency: < 2s

## Code Style

- **Python**: Ruff with 120-char lines, Python 3.10+ target
- **TypeScript/React**: Biome with tab indentation

### Comments

Whenever making a code change that is not immediately obvious — e.g. a workaround, a non-obvious flag, a subtle timing dependency, or a platform-specific fix — add a concise inline comment explaining why it is needed. One to three lines is usually enough. Skip comments where the code is self-evident.

### Status Detection Bug Fix Guidelines

Status detection is this project's most bug-prone area. Fixes here routinely cause regressions — fixing "false approving" by tightening a check can cause "missed approving" in a different scenario. Treat every status change as high-risk.

**The whack-a-mole problem.** Status conditions overlap. The detection logic is a priority chain where each branch assumes the ones above it already filtered out certain states. Changing one branch shifts what falls through to branches below it. Never modify a single condition in isolation — read and reason about the full chain first.

**Before committing any status logic change**, manually verify against ALL of these scenarios (not just the one you're fixing):
- Tool approval pending (user hasn't responded yet)
- User rejected a tool call
- User is typing a reply (Claude waiting)
- Claude is mid-response (thinking/streaming)
- Subagent running
- Hook running
- Session just resumed
- Plan mode active
- User interrupted Claude mid-response

**Comment requirements for status fixes.** Every status condition change must have an inline comment explaining: (1) what scenario this handles, and (2) what false status it prevents. Reference the commit hash or bug that motivated the fix. Example:
```python
# After tool rejection, the JSONL still has a pending tool_use with no result.
# Without this check, _detect_session_status returns "approving" instead of "waiting".
# Fix for: fcedcc5
```

**Never change status logic without reading the full detection chain.** Open the status detection function, read it top to bottom, and understand which scenarios each branch handles before touching anything.

### Real-Time Constraints

This dashboard is a real-time monitor. The user watches it continuously to know which sessions need attention. Stale or delayed data is a bug — it causes missed approvals and wasted time.

- **No sleep for state settling.** Never use `sleep()` / `time.sleep()` to "wait for state to settle" or "let the file finish writing." Instead, detect the correct state directly from the data. The only acceptable use of sleep/delay is debouncing jitter (e.g., the 500ms file-change debounce).
- **SSE updates must reflect current state immediately.** Don't batch, delay, or throttle status changes hoping they'll self-correct.
- **Fix flicker at the source.** If a status flickers between two values, the detection logic has a gap or race. Fix the logic — don't mask it with delays or "sticky" timers that hold the old status.
