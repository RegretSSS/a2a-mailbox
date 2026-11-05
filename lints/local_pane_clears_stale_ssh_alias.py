#!/usr/bin/env python3
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load_mcp():
    spec = importlib.util.spec_from_file_location("mailbox_mcp", ROOT / "mcp" / "mailbox_mcp.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def seed(mcp, workspace, pane, pane_alive):
    os.environ["A2A_MAILBOX_ROOT"] = workspace
    os.environ.pop("TMUX_PANE", None)
    if pane:
        os.environ["TMUX_PANE"] = pane
    from common import registry

    mcp.paths.mailbox_root = lambda: Path(workspace)
    mcp.detect.detect_cli = lambda: "pi"
    mcp.detect.current_pane_id = lambda: pane
    mcp.detect.local_host = lambda: "host-a"
    mcp.detect.tailnet_host = lambda: ""
    mcp.spawn_cmd_from_env = lambda: None
    mcp.ssh_alias_from_env = lambda: ""
    mcp.boot_hub_if_absent = lambda root: None
    mcp.tmuxio.pane_slot = lambda p, ssh=None: "pi:pi-live" if p else ""
    mcp.tmuxio.pane_pid = lambda p, ssh=None: "2010894" if p else ""
    mcp.tmuxio.pane_window_name = lambda p, ssh=None: "pi-live" if p else ""
    mcp.tmuxio.pane_pid_matches = lambda p, pid, ssh=None: bool(p) and pid == "2010894" and pane_alive
    agent_id = mcp.detect.build_agent_id("pi", os.getcwd())
    registry.upsert(Path(workspace), agent_id, {"agent_id": agent_id, "cli": "pi", "cwd": os.getcwd(), "ssh_alias": "host-b"})
    return agent_id


def lint() -> list[str]:
    problems = []
    mcp = load_mcp()
    incident = seed(mcp, tempfile.mkdtemp(prefix="a2a-lint-"), "%49", True)
    record = mcp.register_record()
    if record.get("ssh_alias"):
        problems.append(
            "ssh_alias 错标: 本机活 pane 注册继承了 held 的 host-b 别名——"
            "实测 2026-11-04 pi-host-a-a2a-mailbox 被 held 污染, sweep 持续去 host-b 找本机 pane 判 offline, "
            "队列邮件静默滞留零告警(hub.log 全事件缺席)"
        )
    keepalive = seed(mcp, tempfile.mkdtemp(prefix="a2a-lint-"), "%49", False)
    record2 = mcp.register_record()
    if record2.get("ssh_alias") != "host-b":
        problems.append(
            "ssh_alias 错标: pane 已死(如远端 respawn/dead-agent 延续)时必须保留 held 别名维持身份连续——"
            "误清会让远端 agent 的 ack 跨机查找断链"
        )
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
