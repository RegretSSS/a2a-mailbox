#!/bin/sh
mkdir -p "$HOME/.agents-mailbox/claims"
printf '{"pane_id":"%s","ts":%s}\n' "$TMUX_PANE" "$(date +%s)" > "$HOME/.agents-mailbox/claims/$(basename "$PWD").json"
exec /usr/local/bin/codex --yolo 2>/tmp/codex-tui.err
