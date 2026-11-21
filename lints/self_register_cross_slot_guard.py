#!/usr/bin/env python3
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT = "claude-box-proj"
CODEX_AGENT = "codex-box-proj"


def prepare():
    workspace = tempfile.mkdtemp(prefix="a2a-lint-")
    os.environ["A2A_MAILBOX_ROOT"] = workspace
    os.environ["CLAUDE_CODE_SESSION_ID"] = "aaaabbbb-1111-2222-3333-444444444444"
    (Path(workspace) / "proj").mkdir(exist_ok=True)
    os.chdir(Path(workspace) / "proj")
    sys.path.insert(0, str(ROOT))

    spec = importlib.util.spec_from_file_location("mailbox_mcp", ROOT / "mcp" / "mailbox_mcp.py")
    mailbox_mcp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mailbox_mcp)
    mailbox_mcp.detect.current_pane_id = lambda: "%7"
    mailbox_mcp.detect.detect_cli = lambda: "claude"
    mailbox_mcp.detect.local_host = lambda: "box"
    mailbox_mcp.detect.tailscale_self_name = lambda: ""
    mailbox_mcp.detect.tailnet_host = lambda: ""
    mailbox_mcp.tmuxio.pane_slot = lambda pane, ssh=None: "s:newwin"
    mailbox_mcp.tmuxio.pane_pid = lambda pane, ssh=None: "5000"
    mailbox_mcp.tmuxio.pane_window_name = lambda pane, ssh=None: "newwin"
    mailbox_mcp.boot_hub_if_absent = lambda root: None
    return mailbox_mcp, Path(workspace)


def lint() -> list[str]:
    problems = []
    mailbox_mcp, root = prepare()
    from common import registry

    mailbox_mcp.tmuxio.pane_pid_matches = lambda pane, pid, ssh=None: True

    mailbox_mcp.detect.detect_cli = lambda: "codex"
    mailbox_mcp.codex_anchor_fields = lambda: {}
    registry.upsert(
        root,
        CODEX_AGENT,
        {"cli": "codex", "slot": "s:oldwin", "pane_id": "%1", "pane_pid": "100"},
    )
    try:
        mailbox_mcp.self_register()
        problems.append("异窗双开: 无 multi_instance 声明的 cli 同 id 异窗且宿主 pane 活跃仍静默顶号——身份锚被偷走")
    except RuntimeError as exc:
        if "异窗" not in str(exc):
            problems.append(f"异窗双开: 拒绝报错必须可行动(指明 slot 与处方): {exc}")

    mailbox_mcp.detect.detect_cli = lambda: "claude"
    session_env = os.environ.pop("CLAUDE_CODE_SESSION_ID", "")
    registry.upsert(
        root,
        AGENT,
        {"cli": "claude", "slot": "s:oldwin", "pane_id": "%1", "pane_pid": "100"},
    )
    try:
        mailbox_mcp.self_register()
        problems.append("无痕夺锚: multi_instance cli 缺 session env 仍放行异窗双开——分身无法追溯, 主锚被偷")
    except RuntimeError:
        pass
    if session_env:
        os.environ["CLAUDE_CODE_SESSION_ID"] = session_env

    registry.upsert(
        root,
        AGENT,
        {
            "cli": "claude",
            "slot": "s:oldwin",
            "pane_id": "%1",
            "pane_pid": "100",
            "fingerprint": "conv-keep123",
            "started_at": 42.0,
            "spawn_cmd": ["z"],
        },
    )
    twin = mailbox_mcp.self_register()
    if twin.get("agent_id") != AGENT:
        problems.append(f"分身顶号: 同目录 claude 双开必须共用 agent_id, 实得 {twin.get('agent_id')!r}")
    if twin.get("fingerprint") != "conv-keep123" or twin.get("spawn_cmd") != ["z"]:
        problems.append("分身保真: 双开注册洗掉 fingerprint/spawn_cmd——对话接续链断裂")
    if "aaaabbbb" not in (twin.get("instances") or {}):
        problems.append("分身入表: 双开注册未以 session 短码落 instances——@定向与 who 拆行失效")

    mailbox_mcp.tmuxio.pane_pid_matches = lambda pane, pid, ssh=None: False
    registry.upsert(
        root,
        AGENT,
        {
            "cli": "claude",
            "slot": "s:oldwin",
            "pane_id": "%1",
            "pane_pid": "100",
            "fingerprint": "conv-keep123",
            "started_at": 42.0,
            "spawn_cmd": ["z"],
            "ssh_alias": "host-b",
        },
    )
    record = mailbox_mcp.self_register()
    if record.get("fingerprint") != "conv-keep123" or record.get("started_at") != 42.0:
        problems.append("接续保真: held 已死重建时 fingerprint/started_at 被洗掉——对话接续链断裂")
    if record.get("spawn_cmd") != ["z"] or record.get("ssh_alias") != "host-b":
        problems.append("接续保真: spawn_cmd/ssh_alias 被洗掉——respawn 投递与联邦归属失效")
    return problems


if __name__ == "__main__":
    os.chdir(ROOT)
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
