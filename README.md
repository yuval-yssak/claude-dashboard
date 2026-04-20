# Claude Sessions Dashboard

A live-updating dashboard for monitoring multiple Claude Code sessions across accounts. Track session status, view Claude's task progress, and manage your own notes and todos — all from a single view.

## Features

- **Real-time monitoring** — SSE (Server-Sent Events) push updates with file-watching via watchdog
- **Multi-account support** — watches multiple Claude config directories simultaneously
- **Session status detection** — identifies thinking, waiting, subagent, hook, approving, and idle states
- **Process tree analysis** — detects subagents, hooks, and tool execution via child process inspection
- **User annotations** — per-session notes and todo lists that persist across restarts
- **Claude task tracking** — displays Claude's internal TodoWrite tasks with progress bars
- **Session management** — focus/resume sessions directly from the dashboard
- **Mobile responsive** — monitoring optimized for phone screens
- **PWA installable** — install as a standalone app on desktop or mobile (requires HTTPS)
- **Background service** — runs as a macOS launchd agent (no terminal required)
- **Cross-device access** — accessible from any device via Tailscale mesh VPN + HTTPS (Tailscale Serve)

## Architecture

```
┌─────────────┐     SSE (push)     ┌──────────────┐
│   Browser    │◄──────────────────│   Python      │
│  (React 19)  │                   │  HTTP Server  │
│              │───REST (mutate)──►│  (threaded)   │
└─────────────┘                    └──────┬───────┘
                                          │
                          ┌───────────────┼───────────────┐
                          │               │               │
                    ┌─────▼─────┐  ┌──────▼──────┐ ┌──────▼──────┐
                    │  watchdog  │  │  JSONL files │ │  ps / proc  │
                    │  (fsevents)│  │  (~/.claude/) │ │  (PID check)│
                    └───────────┘  └─────────────┘ └─────────────┘
```

**Backend** (`server/`): Python stdlib `ThreadingHTTPServer`. The orchestrator `claude_dashboard.py` owns session collection, state detection, the watchdog/periodic refresh loop, SSE broadcasting, and serving the React SPA from `client/dist/`. Pure-utility modules sit alongside it:

- `jsonl_scan.py` — tail-parse JSONL files in `~/.claude/projects/**/*.jsonl`
- `process_monitor.py` — PID liveness, CPU, and process-tree inspection
- `query_helpers.py` — on-disk reads (rate limits, account email)
- `annotations.py` — per-session notes/todos persistence (atomic + thread-safe)
- `config.py` — constants and thresholds
- `utils.py` — formatting helpers (`friendly_project_name`, `time_ago`)

**Frontend** (`client/`): React 19 + TypeScript + Vite SPA that:
- Connects to `/api/events` via EventSource for real-time updates
- Displays sessions grouped by account with status indicators
- Provides per-session notes and todo management

## Quick Start (Local Development)

```bash
# Install dependencies
pip3 install watchdog
cd client && npm install

# Start backend (in one terminal)
python3 server/claude_dashboard.py

# Start frontend dev server (in another terminal)
cd client && npm run dev
```

The dev server runs on `http://localhost:5173` with a proxy to the backend on port 8484.

## Deploy as Background Service

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for full instructions, or use the quick install:

```bash
./deploy/install.sh
```

This installs dependencies, builds the frontend, and registers a macOS launchd service that starts on login and auto-restarts on crash.

### HTTPS + PWA Install

To access over HTTPS (required for PWA install on mobile):

```bash
tailscale serve --bg --https=443 http://localhost:8484
```

Then open `https://<machine-name>.<tailnet>.ts.net` on your phone and install as an app.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.10+ (stdlib `http.server`, `threading`) |
| File watching | [watchdog](https://github.com/gorakhargosh/watchdog) (optional, graceful fallback) |
| Frontend | React 19, TypeScript, Vite |
| Linting | [Biome](https://biomejs.dev/) (frontend), [Ruff](https://github.com/astral-sh/ruff) (backend) |
| Deployment | macOS launchd + [Tailscale](https://tailscale.com/) (Serve for HTTPS) |

## Project Structure

```
claude-dashboard/
├── server/
│   ├── claude_dashboard.py    # HTTP/SSE server, session collection, state detection
│   ├── jsonl_scan.py          # JSONL tail parsing
│   ├── process_monitor.py     # PID/CPU/process-tree probing
│   ├── query_helpers.py       # On-disk read helpers (rate limits, account email)
│   ├── annotations.py         # Notes/todos persistence
│   ├── config.py              # Constants and thresholds
│   ├── utils.py               # Pure formatters
│   ├── requirements.txt       # Python dependencies
│   └── ruff.toml              # Python linter config
├── client/
│   ├── src/                   # React source code
│   ├── biome.json             # TypeScript/React linter config
│   ├── package.json
│   └── vite.config.ts
├── deploy/
│   ├── com.yuval.claude-dashboard.plist  # launchd service definition
│   └── install.sh                        # One-command install script
├── docs/
│   ├── DEPLOYMENT.md          # Deployment guide
│   └── TESTING.md             # Test case catalog
└── README.md
```

## Configuration

Environment variables (all optional):

| Variable | Default | Description |
|----------|---------|-------------|
| `CLAUDE_DASHBOARD_PORT` | `8484` | HTTP server port |
| `CLAUDE_CONFIGS` | `~/.claude,~/.claude-personal` | Comma-separated config directories to watch |

## Warp Tab Focus Notes

Clicking "focus" on a live Warp session asks macOS to switch to the tab where `claude` is running. Warp has no AppleScript dictionary and no URI-scheme action for focusing an existing tab ([warpdotdev/warp#8611](https://github.com/warpdotdev/warp/issues/8611)), so the dashboard raises each Warp window in turn and cycles its tabs with `Cmd+Shift+]` via System Events, matching the stripped tab title (leading activity glyph ignored) against an ordered candidate list: `claude:<session_id>`, Claude session name, `<parent>/<basename>` of the cwd, cwd basename. Matching is exact (or a truncation-suffix match when Warp shows a long title as `..<suffix>`) — not substring. The first pass only accepts the two **strong** candidates (`claude:<id>`, session name); cwd-derived candidates are tried only if no strong match exists anywhere, since multiple tabs can share a cwd title.

### Disambiguating sessions that share a cwd (recommended)

Warp's default tab title is the cwd basename, so two Claude sessions in the same directory (e.g. two `bot-launcher` sessions) produce two tabs with identical titles — the dashboard can't tell them apart and may focus the wrong one. When it detects this case, it shows a warning toast pointing at this section.

To fix it permanently, install a `SessionStart` hook that tags each tab with `claude:<session_id>` on startup. Candidate #1 then matches unambiguously:

1. Copy the hook into your `~/.claude/hooks/` directory:
   ```sh
   mkdir -p ~/.claude/hooks
   cp deploy/hooks/set-warp-tab-title.sh ~/.claude/hooks/
   chmod +x ~/.claude/hooks/set-warp-tab-title.sh
   ```
2. Register it in `~/.claude/settings.json` under `hooks`:
   ```json
   "SessionStart": [
     { "matcher": "", "hooks": [{ "type": "command", "command": "~/.claude/hooks/set-warp-tab-title.sh" }] }
   ]
   ```
3. Start new Claude sessions (or resume existing ones) so the hook fires — each Warp tab's title becomes `claude:<session_id>`.

The hook writes the OSC 2 title escape directly to `/dev/tty`, so it works even though Claude Code captures hook stdout.

## License

MIT
