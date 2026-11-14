SPEC = {
    "cli": "claude",
    "proc_names": ("claude",),
    "pane_commands": ("claude", "node"),
    "delivery_kind": "tmux",
    "wake_cap": True,
    "respawn": {"backend": "tmux", "resume_args": ["-c"]},
    "multi_instance": {"key": "session"},
    "notes": "无原生注入接口, tmux 粘贴为主通道; TUI 2.1.312+ 超长注入折叠 paste blob(唯一实证, wake_cap 唯一持有者); 恢复=tmux respawn 固定窗跑 claude -c; 同目录多实例以 CLAUDE_CODE_SESSION_ID 追溯",
}
