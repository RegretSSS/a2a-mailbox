SPEC = {
    "cli": "codex",
    "proc_names": ("codex",),
    "delivery_kind": "queue-daemon",
    "notes": "codex queue --thread 经 app-server daemon 入原生队列; 锚定失效/daemon 死亡/命令失败降级 tmux",
}
