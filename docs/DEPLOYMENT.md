# Deployment Guide

This guide covers deploying the Claude Sessions Dashboard as a background service accessible from any device.

## Prerequisites

- macOS (launchd is macOS-only)
- Python 3.10+
- Node.js 18+
- [Tailscale](https://tailscale.com/) (for cross-device access)

## Quick Install

```bash
cd claude-dashboard
./deploy/install.sh
```

This script:
1. Installs Python dependencies (`watchdog`)
2. Installs Node dependencies and builds the React frontend
3. Configures a `statusLine` hook in each Claude config's `settings.json` so the dashboard can capture rate-limit/usage data (see [Statusline capture](#statusline-capture-rate-limit-data) below)
4. Renders `deploy/com.yuval.claude-dashboard.plist.template` with your local paths and writes it to `~/Library/LaunchAgents/`
5. Loads the service (starts immediately)

## Statusline capture (rate-limit data)

Step 3 of `install.sh` writes a `statusLine` entry into `settings.json` for each directory in `CLAUDE_CONFIGS` (default: `~/.claude`, `~/.claude-personal`). The entry runs `deploy/statusline-capture.sh`, which persists rate-limit info to `rate-limits.json` alongside the server so the dashboard can display per-account usage.

If a `settings.json` already has a `statusLine` set to something else, the installer prints a warning and overwrites it — back up your custom statusline first if you want to restore it later.

To opt out, run the installer with an empty config list:

```bash
CLAUDE_CONFIGS="" ./deploy/install.sh
```

Or remove the `statusLine` block from your `settings.json` after install.

## Manual Install

### 1. Install Dependencies

```bash
pip3 install watchdog

cd client
npm install
npm run build
```

### 2. Test Locally

```bash
python3 server/claude_dashboard.py
# Open http://localhost:8484
```

### 3. Install as launchd Service

The committed file `deploy/com.yuval.claude-dashboard.plist.template` contains `__PYTHON__`, `__SCRIPT__`, and `__LOG__` placeholders. Render them for your machine and install:

```bash
sed \
    -e "s|__PYTHON__|$(command -v python3)|g" \
    -e "s|__SCRIPT__|$PWD/server/claude_dashboard.py|g" \
    -e "s|__LOG__|$HOME/Library/Logs/claude-dashboard.log|g" \
    deploy/com.yuval.claude-dashboard.plist.template \
    > ~/Library/LaunchAgents/com.yuval.claude-dashboard.plist
launchctl load ~/Library/LaunchAgents/com.yuval.claude-dashboard.plist
```

### 4. Verify

```bash
# Check service is running
launchctl list | grep claude-dashboard
# Should show: <PID>  0  com.yuval.claude-dashboard

# Check HTTP
curl http://localhost:8484/api/sessions | python3 -m json.tool | head
```

## Tailscale Setup (Cross-Device Access)

Tailscale creates a private mesh VPN so you can access the dashboard from your phone or any other device — even when they're on different networks.

### On your Mac

```bash
brew install --cask tailscale
```

Open Tailscale from Applications, sign in, and note your Tailscale FQDN:

```bash
tailscale status --self
# Shows: 100.x.x.x  yuvals-macbook  ...
```

### HTTPS via Tailscale Serve

Tailscale Serve proxies HTTPS traffic to your local HTTP server with a valid TLS certificate. This is required for PWA installation on mobile devices.

```bash
tailscale serve --bg --https=443 http://localhost:8484
```

This makes the dashboard available at `https://<machine-name>.<tailnet>.ts.net` with automatic TLS.

To find your full URL:

```bash
tailscale status --json | grep MagicDNSSuffix
# Returns your tailnet suffix, e.g. tail1f8fda.ts.net
```

Your dashboard URL: `https://<machine-name>.<tailnet-suffix>`

To stop the proxy:

```bash
tailscale serve --https=443 off
```

> **Note:** Tailscale Serve must be enabled on your tailnet. If you get an error, the CLI will provide a link to enable it in the admin console.

### On your phone

1. Install Tailscale from App Store / Play Store
2. Sign in with the same account
3. Open `https://<machine-name>.<tailnet>.ts.net` in Chrome
4. Tap the menu (⋮) → **"Install app"** to install as a PWA

## Configuration

### Environment Variables

Set these in `deploy/com.yuval.claude-dashboard.plist.template` under `EnvironmentVariables` (then re-run `./deploy/install.sh` to re-render and reload):

| Variable | Default | Description |
|----------|---------|-------------|
| `CLAUDE_DASHBOARD_PORT` | `8484` | HTTP server port |
| `CLAUDE_CONFIGS` | `~/.claude,~/.claude-personal` | Config directories to watch |

Example plist change:
```xml
<key>EnvironmentVariables</key>
<dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    <key>CLAUDE_DASHBOARD_PORT</key>
    <string>9090</string>
    <key>CLAUDE_CONFIGS</key>
    <string>~/.claude</string>
</dict>
```

After changing the plist, reload the service:
```bash
launchctl unload ~/Library/LaunchAgents/com.yuval.claude-dashboard.plist
launchctl load ~/Library/LaunchAgents/com.yuval.claude-dashboard.plist
```

## Service Management

```bash
# Start
launchctl load ~/Library/LaunchAgents/com.yuval.claude-dashboard.plist

# Stop
launchctl unload ~/Library/LaunchAgents/com.yuval.claude-dashboard.plist

# Restart
launchctl unload ~/Library/LaunchAgents/com.yuval.claude-dashboard.plist
launchctl load ~/Library/LaunchAgents/com.yuval.claude-dashboard.plist

# Check status
launchctl list | grep claude-dashboard

# View logs
tail -f ~/Library/Logs/claude-dashboard.log
```

### Rebuild + restart after code changes

After editing **frontend** code, rebuild the client bundle before restarting — the launchd service serves `client/dist/`, so a restart alone won't pick up source changes:

```bash
cd client && npm run build
launchctl kickstart -k gui/$(id -u)/com.yuval.claude-dashboard
```

After editing **backend** code (`server/*.py`), just kickstart:

```bash
launchctl kickstart -k gui/$(id -u)/com.yuval.claude-dashboard
```

`launchctl kickstart -k` is preferred over `unload` + `load` because it restarts the running job in place and avoids a brief window where the service is unregistered.

A convenient shell alias for the full frontend rebuild + restart:

```bash
alias restart-dashboard='cd /path/to/claude-dashboard/client && npm run build && cd - > /dev/null && launchctl kickstart -k gui/$(id -u)/com.yuval.claude-dashboard'
```

## Troubleshooting

### Port already in use

```bash
lsof -ti:8484 | xargs kill
# Then restart the service
```

### Service won't start

Check the log file:
```bash
cat ~/Library/Logs/claude-dashboard.log
```

Common issues:
- Wrong Python path in plist (check with `which python3`)
- Missing dependencies (`pip3 install watchdog`)
- Frontend not built (`cd client && npm run build`)

### watchdog not working

If watchdog isn't installed, the server falls back to periodic-only mode (refreshes every 5 seconds instead of reacting to file changes). Install it:

```bash
pip3 install watchdog
```

### Dashboard loads but shows no sessions

- Check that `CLAUDE_CONFIGS` points to valid directories
- Verify sessions exist: `ls ~/.claude/projects/*/sessions.json`
- Check that session JSONL files are not older than 7 days (old sessions are filtered out)
