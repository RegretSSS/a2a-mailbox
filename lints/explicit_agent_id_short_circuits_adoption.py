#!/usr/bin/env python3
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CLAIMED_PANE = "%9"
CLAIMED_PID = "1487"
CLAIMED_SLOT = "claude"
HELD_AGENT = "claude-host-a-a2a-mailbox"
DSH_AGENT = "dsh-host-a-wsl"


def load_mcp():
    spec = importlib.util.spec_from_file_location("mailbox_mcp", ROOT / "mcp" / "mailbox_mcp.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def seed(mcp, workspace: str, cwd: str):
    os.environ["A2A_MAILBOX_ROOT"] = workspace
    os.environ.pop("TMUX_PANE", None)
    os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
    mcp.paths.mailbox_root = lambda: Path(workspace)
    mcp.detect.current_pane_id = lambda: CLAIMED_PANE
    mcp.detect.local_host = lambda: "host-a"
    mcp.detect.tailnet_host = lambda: ""
    mcp.spawn_cmd_from_env = lambda: None
    mcp.ssh_alias_from_env = lambda: ""
    mcp.boot_hub_if_absent = lambda root: None
    mcp.tmuxio.pane_pid = lambda pane, ssh=None: CLAIMED_PID if pane == CLAIMED_PANE else ""
    mcp.tmuxio.pane_slot = lambda pane, ssh=None: CLAIMED_SLOT if pane == CLAIMED_PANE else ""
    mcp.tmuxio.pane_window_name = lambda pane, ssh=None: CLAIMED_SLOT if pane == CLAIMED_PANE else ""
    mcp.tmuxio.pane_pid_matches = lambda pane, pid, ssh=None: pane == CLAIMED_PANE and pid == CLAIMED_PID
    os.chdir(cwd)
    mcp.registry.upsert(
        Path(workspace),
        HELD_AGENT,
        {
            "agent_id": HELD_AGENT,
            "cli": "claude",
            "host": "host-a",
            "cwd": cwd,
            "slot": CLAIMED_SLOT,
            "pane_id": CLAIMED_PANE,
            "pane_pid": CLAIMED_PID,
        },
    )


def lint() -> list[str]:
    problems = []
    mcp = load_mcp()
    workspace = tempfile.mkdtemp(prefix="a2a-lint-mbx-")
    cwd = tempfile.mkdtemp(prefix="a2a-lint-cwd-")
    seed(mcp, workspace, cwd)
    os.environ["A2A_AGENT_ID"] = DSH_AGENT
    os.environ["A2A_CLI"] = "dsh"
    record = mcp.register_record()
    if record.get("agent_id") != DSH_AGENT:
        problems.append(
            f"显式身份被认领链吞并: A2A_AGENT_ID={DSH_AGENT} 时注册出 {record.get('agent_id')!r}——"
            "实测 2026-11-08 dsh web host 的 MCP 进程(cwd=deepseek-harness, pane 经 claims 认领) "
            "顶名 claude-host-a-a2a-mailbox 发信(from=claude 档, msg c8f45/1b9f), dsh 档零注册; "
            "显式身份必须短路会话证明与 slot+cwd 全部认领段"
        )
    if record.get("cli") != "dsh":
        problems.append(f"显式身份 CLI 覆盖失效: A2A_CLI=dsh 注册出 cli={record.get('cli')!r}")

    workspace2 = tempfile.mkdtemp(prefix="a2a-lint-mbx-")
    seed(mcp, workspace2, cwd)
    os.environ.pop("A2A_AGENT_ID", None)
    os.environ.pop("A2A_CLI", None)
    record2 = mcp.register_record()
    if record2.get("agent_id") != HELD_AGENT:
        problems.append(
            f"认领行为被误伤: 无显式身份时 slot+cwd 匹配应照旧 adopt {HELD_AGENT}, 实得 {record2.get('agent_id')!r}"
        )
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
