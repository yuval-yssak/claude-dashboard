#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PLIST_NAME="com.yuval.claude-dashboard"
PLIST_TEMPLATE="$SCRIPT_DIR/$PLIST_NAME.plist.template"
PLIST_DST="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"
LOG_FILE="$HOME/Library/Logs/claude-dashboard.log"
PYTHON_BIN="$(command -v python3)"
SERVER_SCRIPT="$PROJECT_DIR/server/claude_dashboard.py"

echo "Claude Sessions Dashboard — Install"
echo "======================================"
echo ""

# 1. Install Python dependencies
echo "[1/5] Installing Python dependencies..."
pip3 install -q watchdog
echo "  Done."

# 2. Install Node dependencies and build client
echo "[2/5] Building frontend..."
cd "$PROJECT_DIR/client"
npm install --silent
npm run build
echo "  Done."

# 3. Configure statusline capture for rate-limit data
echo "[3/5] Configuring statusline capture..."
CAPTURE_SCRIPT="$SCRIPT_DIR/statusline-capture.sh"
chmod +x "$CAPTURE_SCRIPT"
for config_dir in $(echo "${CLAUDE_CONFIGS:-$HOME/.claude,$HOME/.claude-personal}" | tr ',' ' '); do
    config_dir="$(eval echo "$config_dir")"  # expand ~
    settings="$config_dir/settings.json"
    if [ -d "$config_dir" ]; then
        python3 -c "
import json, sys, os

settings_path = '$settings'
capture_cmd = '$CAPTURE_SCRIPT $config_dir'

# Read existing settings or start fresh
data = {}
if os.path.exists(settings_path):
    with open(settings_path) as f:
        data = json.load(f)

# Check for existing statusLine
existing = data.get('statusLine')
if existing:
    existing_cmd = existing.get('command', '')
    if 'statusline-capture.sh' in existing_cmd:
        print(f'  {settings_path}: already configured')
        sys.exit(0)
    else:
        print(f'  WARNING: {settings_path} has an existing statusLine command:')
        print(f'    {existing_cmd}')
        print(f'  Overwriting with dashboard capture script.')

data['statusLine'] = {'type': 'command', 'command': capture_cmd}

tmp = settings_path + '.tmp'
with open(tmp, 'w') as f:
    json.dump(data, f, indent=2)
    f.write('\n')
os.replace(tmp, settings_path)
print(f'  {settings_path}: statusLine configured')
"
    fi
done
echo "  Done."

# 4. Unload existing service if running
if launchctl list "$PLIST_NAME" &>/dev/null; then
    echo "[4/5] Stopping existing service..."
    launchctl unload "$PLIST_DST" 2>/dev/null || true
else
    echo "[4/5] No existing service found."
fi

# 5. Render and load plist
echo "[5/5] Installing launchd service..."
mkdir -p "$(dirname "$LOG_FILE")"
mkdir -p "$(dirname "$PLIST_DST")"
# Render the plist template with this machine's paths so the service works
# regardless of clone location or user. sed uses | as delimiter because the
# replacement values contain /.
sed \
    -e "s|__PYTHON__|$PYTHON_BIN|g" \
    -e "s|__SCRIPT__|$SERVER_SCRIPT|g" \
    -e "s|__LOG__|$LOG_FILE|g" \
    "$PLIST_TEMPLATE" > "$PLIST_DST"
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
