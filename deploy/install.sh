#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PLIST_NAME="com.yuval.claude-dashboard"
PLIST_SRC="$SCRIPT_DIR/$PLIST_NAME.plist"
PLIST_DST="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"

echo "Claude Sessions Dashboard — Install"
echo "======================================"
echo ""

# 1. Install Python dependencies
echo "[1/4] Installing Python dependencies..."
pip3 install -q watchdog
echo "  Done."

# 2. Install Node dependencies and build client
echo "[2/4] Building frontend..."
cd "$PROJECT_DIR/client"
npm install --silent
npm run build
echo "  Done."

# 3. Unload existing service if running
if launchctl list "$PLIST_NAME" &>/dev/null; then
    echo "[3/4] Stopping existing service..."
    launchctl unload "$PLIST_DST" 2>/dev/null || true
else
    echo "[3/4] No existing service found."
fi

# 4. Install and load plist
echo "[4/4] Installing launchd service..."
cp "$PLIST_SRC" "$PLIST_DST"
launchctl load "$PLIST_DST"
echo "  Done."

echo ""
echo "Dashboard is now running as a background service."
echo "  URL:  http://localhost:8484"
echo "  Logs: ~/Library/Logs/claude-dashboard.log"
echo ""
echo "To check status:  launchctl list | grep claude-dashboard"
echo "To stop:          launchctl unload ~/Library/LaunchAgents/$PLIST_NAME.plist"
echo "To restart:       launchctl unload ~/Library/LaunchAgents/$PLIST_NAME.plist && launchctl load ~/Library/LaunchAgents/$PLIST_NAME.plist"
