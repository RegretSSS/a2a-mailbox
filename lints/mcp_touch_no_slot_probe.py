#!/usr/bin/env python3
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALICE = "claude-host-a-a2a-mailbox"
BOB = "pi-host-a-a2a-mailbox"


def prepare():
    workspace = tempfile.mkdtemp(prefix="a2a-lint-")
    os.environ["A2A_MAILBOX_ROOT"] = workspace
    os.environ["A2A_HOST_TAG"] = "lint"
    sys.path.insert(0, str(ROOT))
    from common import registry

    spec = importlib.util.spec_from_file_location("mailbox_mcp", ROOT / "mcp" / "mailbox_mcp.py")
    mailbox_mcp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mailbox_mcp)
    for agent_id in (ALICE, BOB):
        registry.upsert(Path(workspace), agent_id, {"cli": "codex", "pane_id": "%1", "pane_pid": "1"})
    return mailbox_mcp, Path(workspace)


def lint() -> list[str]:
    problems = []
    mailbox_mcp, root = prepare()
    probes = {"pane_slot": 0, "upsert": 0}
    original_pane_slot = mailbox_mcp.tmuxio.pane_slot
    original_upsert = mailbox_mcp.registry.upsert

    def counting_pane_slot(*args, **kwargs):
        probes["pane_slot"] += 1
        return "moved:renamed-window"

    def counting_upsert(*args, **kwargs):
        probes["upsert"] += 1
        return original_upsert(*args, **kwargs)

    mailbox_mcp.tmuxio.pane_slot = counting_pane_slot
    mailbox_mcp.registry.upsert = counting_upsert
    try:
        sent = json.loads(mailbox_mcp.do_send(ALICE, BOB, "任务: 读 DESIGN.md 决策记录并回函"))
    finally:
        mailbox_mcp.tmuxio.pane_slot = original_pane_slot
        mailbox_mcp.registry.upsert = original_upsert
    if not sent.get("ok"):
        problems.append(f"MCP touch 面: 发送失败 {sent}")
    if probes["pane_slot"]:
        problems.append(
            f"MCP touch 面: 工具调用路径探测 slot {probes['pane_slot']} 次——rename/漂移检测归 hub 节点, MCP 只注册一次+touch 心跳"
        )
    if probes["upsert"]:
        problems.append(
            f"MCP touch 面: 工具调用路径触发重注册 upsert {probes['upsert']} 次——漂移接管只许发生在 MCP 启动注册时"
        )
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
