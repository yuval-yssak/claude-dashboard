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
3. Copies the launchd plist to `~/Library/LaunchAgents/`
4. Loads the service (starts immediately)

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

```bash
cp deploy/com.yuval.claude-dashboard.plist ~/Library/LaunchAgents/
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

Set these in the launchd plist (`deploy/com.yuval.claude-dashboard.plist`) under `EnvironmentVariables`:

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

### Customizing for Your System

If you're deploying this on a different machine:

1. Update `ProgramArguments` in the plist to point to your `python3` binary:
   ```bash
   which python3
   # Use this path in the plist
   ```

2. Update the script path in `ProgramArguments` to your clone location

3. Update `StandardOutPath` and `StandardErrorPath` for your home directory

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
