#!/bin/sh
LOG=~/workspace/a2a-mailbox/.monitor.log
while true; do
  {
    echo; echo "##### $(date +%F\ %H:%M:%S)"
    for w in claude codex pi pi-r codexwin a2a-cc; do
      echo "--- pi:$w ---"
      tmux capture-pane -p -t "pi:$w" 2>/dev/null | grep -v "^$" | tail -3
    done
    echo "--- git ---"
    git -C ~/workspace/a2a-mailbox log --oneline -3 2>/dev/null
  } >> "$LOG" 2>&1
  sleep 45
done
