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

## Architecture

```
Browser (React 19 + TypeScript)
  ↕ REST + SSE
Python 3 HTTP Server (stdlib http.server + threading)
  ↕ watchdog (FSEvents) + ps/pgrep
~/.claude/ and ~/.claude-personal/ JSONL files + process tree
```

**Backend** (`server/claude_dashboard.py`, single file):
- Scans JSONL files in `~/.claude/projects/*/` to collect sessions
- Monitors PIDs, CPU, child processes to determine session liveness and activity
- Detects session state by analyzing JSONL tail (last 2000 lines): thinking, waiting, approving, idle, etc.
- Inspects process tree for subagents, hooks, tool execution
- File watching via watchdog (500ms debounce) + periodic 5s refresh
- SSE streaming to all connected clients with version-tracked cache
- Session resumption via AppleScript (Warp tabs, other apps)
- Persists user annotations (notes/todos) to `claude-dashboard-data.json` with atomic file replace + thread locking

**Frontend** (`client/src/`):
- `App.tsx` — SSE connection, global state
- `components/` — Header, AccountSection (drag-drop grid), SessionCard, AnnotationsPanel, ClaudeTodos, StatusBadge, SummaryBar, Toast
- `hooks/` — useSSE (EventSource), useDebouncedSave, useCardOrdering (drag-drop + pinning via @dnd-kit)
- Mobile-responsive (single column < 920px, read-only on mobile)
- PWA-installable (manifest + no-op service worker, no offline support — app requires live SSE connection)

## Session State Detection

State priority: `subagent > hook > approving > thinking > waiting > idle > inactive`

The backend combines JSONL analysis (conversational state) with process tree inspection (activity detection). IDE events from VS Code are filtered out. Messages < 2s old are treated as still streaming.

### Session Sort Order

Sessions are sorted by backend status rank (primary) and `last_activity` descending (secondary):

| Rank | Status | Meaning |
|------|--------|---------|
| 0 | `approving` | Waiting for user permission approval |
| 1 | `waiting` | Claude done, waiting for user reply |
| 2 | `thinking`, `subagent`, `hook` | Active work — don't leapfrog each other |
| 3 | `recent` | Dead process, last activity < 5 min ago |
| 4 | `idle` | Dead process, last activity 5 min – 2 hours ago |
| — | `inactive`, `unknown` | Filtered out; not displayed |

Within the same rank, sessions maintain relative position by `last_activity` timestamp (newest first).

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
