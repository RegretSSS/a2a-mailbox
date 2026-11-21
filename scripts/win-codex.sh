#!/bin/sh
export WSLENV=TMUX_PANE:TMUX
cd /mnt/c/Users/user-a/win-codex-ws
mkdir -p "$HOME/.agents-mailbox/claims"
printf '{"pane_id":"%s","ts":%s}\n' "$TMUX_PANE" "$(date +%s)" > "$HOME/.agents-mailbox/claims/$(basename "$PWD").json"
exec /mnt/c/Windows/System32/cmd.exe /c "C:\Users\user-a\codex-dev-launch.cmd"
