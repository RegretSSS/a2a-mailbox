#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="${1:-host-b}"

rsync -az --delete \
  --exclude .git/ \
  --exclude __pycache__/ \
  --exclude .pytest_cache/ \
  --exclude .hub-dev.log \
  --exclude .monitor.log \
  ./ "$REMOTE_HOST:workspace/a2a-mailbox/"

ssh "$REMOTE_HOST" bash -s <<'REMOTE'
set -euo pipefail
cd "$HOME/workspace/a2a-mailbox"
python3 -c "import fastmcp" >/dev/null 2>&1 || { echo "deploy abort: fastmcp missing"; exit 1; }
python3 -m pytest tests/ -q 2>&1 | tail -1
if [ -d "$HOME/.pi/agent" ]; then
  mkdir -p "$HOME/.pi/agent/extensions"
  cp pi/a2a-inbox.ts "$HOME/.pi/agent/extensions/a2a-inbox.ts"
  echo "pi extension synced"
fi
mkdir -p "$HOME/.config/systemd/user"
cp deploy/a2a-hub.service "$HOME/.config/systemd/user/a2a-hub.service"
systemctl --user stop a2a-hub.service 2>/dev/null || true
pkill -f "hub/hub.py" 2>/dev/null || true
sleep 1
systemctl --user daemon-reload
systemctl --user enable a2a-hub.service >/dev/null
systemctl --user restart a2a-hub.service
sleep 1
systemctl --user is-active a2a-hub.service
journalctl --user -u a2a-hub.service -n 3 --no-pager
MAGPIE_BIN="$(command -v magpie-cli || command -v magpie || true)"
if [ -n "$MAGPIE_BIN" ] && [ -f "$HOME/.agents-mailbox/registry.json" ]; then
  "$MAGPIE_BIN" plugin add "$HOME/workspace/a2a-mailbox/plugins/gateway-mailbox" 2>&1 | tail -1
else
  echo "magpie not found on this host: gateway-mailbox hook not installed"
fi
REMOTE
