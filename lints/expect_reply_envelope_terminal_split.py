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
    from common import storage

    sent = json.loads(mailbox_mcp.do_send(ALICE, BOB, "任务: 读 DESIGN.md 并回函", expect_reply=True))
    if not sent.get("ok"):
        problems.append(f"expect_reply: 发送失败 {sent}")
        return problems
    queued = storage.list_queue(root, BOB)
    envelope = queued[0] if queued else {}
    if envelope.get("expect_reply") is not True:
        problems.append("expect_reply: 字段未落 envelope——hub 终态无法分叉, 『需回函』承诺形同虚设")
    if not str(envelope.get("wake_text", "")).rstrip().endswith("]"):
        problems.append("expect_reply: 唤醒词尾缺回函短标记——收件方无从得知需要回函")
    plain = json.loads(mailbox_mcp.do_send(ALICE, BOB, "回执: expect_reply 通知腿OK"))
    if not plain.get("ok"):
        problems.append(f"expect_reply: 通知腿发送失败 {plain}")
    second = storage.list_queue(root, BOB)[1]
    if second.get("expect_reply") is not False:
        problems.append("expect_reply: 通知腿缺省必须显式 False——老信封 .get 缺省语义要可区分")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
