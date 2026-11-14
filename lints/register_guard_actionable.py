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
    sys.path.insert(0, str(ROOT))
    from common import registry

    spec = importlib.util.spec_from_file_location("mailbox_mcp", ROOT / "mcp" / "mailbox_mcp.py")
    mailbox_mcp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mailbox_mcp)
    root = Path(workspace)
    for agent_id in (ALICE, BOB):
        registry.upsert(root, agent_id, {"cli": "pi", "pane_id": "%1", "pane_pid": "1"})
    mailbox_mcp.boot_hub_if_absent = lambda root_path: None
    return mailbox_mcp, root


def lint() -> list[str]:
    problems = []
    mailbox_mcp, root = prepare()
    calls = {"register": 0}
    mailbox_mcp.SELF = {}

    def blocked_register(mounted_id: str = ""):
        calls["register"] += 1
        raise RuntimeError("slot s:old 已有活跃对话(x), 同 tmux 名禁止双开——换窗名再启动")

    mailbox_mcp.self_register = blocked_register
    blocked = json.loads(mailbox_mcp.mail_who())
    if blocked.get("ok") is not False:
        problems.append(f"注册守卫: SELF 空时工具必须拒绝: {blocked}")
    elif "已有活跃对话" not in str(blocked.get("error")) or "换 tmux 窗名" not in str(blocked.get("error")):
        problems.append(f"注册守卫: 报错必须带真实原因与处方(换窗名自愈)——『未完成自注册』教 agent 死等: {blocked}")

    healed = {"agent_id": ALICE, "pane_id": "%1"}
    mailbox_mcp.self_register = lambda mounted_id="": (calls.__setitem__("register", calls["register"] + 1) or healed)
    verdict = json.loads(mailbox_mcp.mail_who())
    if not verdict.get("ok") or mailbox_mcp.SELF is not healed:
        problems.append("注册守卫: 空 SELF 必须惰性重试一次——换窗名后免重启 CLI 自愈是唯一恢复通道")
    before = calls["register"]
    json.loads(mailbox_mcp.mail_who())
    if calls["register"] != before:
        problems.append("注册守卫: SELF 已就位仍重跑注册——漂移接管禁区(mcp_touch_no_slot_probe)")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
