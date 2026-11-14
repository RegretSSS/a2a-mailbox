SPEC = {
    "cli": "pi",
    "proc_names": ("pi",),
    "delivery_kind": "native-inbox",
    "respawn": {"backend": "direct", "resume_args": ["-c"]},
    "multi_instance": {"key": "pane"},
    "notes": "a2a-inbox.ts 扩展 sendUserMessage 原生队列; rcpt 回执+alive 心跳, 缺席降级 tmux; 恢复=后台直拉; 同目录多实例以 tmux pane 追溯",
}
