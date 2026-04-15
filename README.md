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

## License

MIT
