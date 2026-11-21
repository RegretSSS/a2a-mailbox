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
    root = Path(workspace)
    for agent_id in (ALICE, BOB, "pi-node-9-third"):
        registry.upsert(root, agent_id, {"cli": "pi", "pane_id": "%1", "pane_pid": "1"})
    mailbox_mcp.boot_hub_if_absent = lambda root_path: None
    return mailbox_mcp, root


def lint() -> list[str]:
    problems = []
    mailbox_mcp, root = prepare()
    from common import msgfmt, storage

    deep_id = "deep000000001"
    storage.enqueue(root, {"msg_id": deep_id, "ack_id": f"ack-{deep_id}", "from": ALICE, "to": BOB,
                           "body": "去哪读: plans/deep.md", "hop": msgfmt.HOP_WARNING_THRESHOLD + 5,
                           "created_at": 1.0,
                           "wake_text": msgfmt.compose_wake(ALICE, deep_id, "去哪读: plans/deep.md")})
    deep = json.loads(mailbox_mcp.do_send(BOB, ALICE, "回函: 深链继续OK", in_reply_to=deep_id))
    if not deep.get("ok"):
        problems.append(f"会话深度: hop 硬拒复辟——深度会话被掐(准则4 给AGENT自由): {deep}")
    elif "hop_warning" not in deep:
        problems.append("会话深度: 超阈值必须附 hop_warning 观测(风暴可见性)")

    for _ in range(storage.RATE_MAX_PER_WINDOW):
        mailbox_mcp.do_send(ALICE, BOB, "回函: ping")
    counter = json.loads(mailbox_mcp.do_send(BOB, ALICE, "回函: pong"))
    if counter.get("ok"):
        problems.append("穿线风暴: 无向对称限速未截 A↔B 乒乓——MAX_HOPS 硬闸已撤, 对称账本是唯一断路器")
    elif "可重试" not in str(counter.get("error")):
        problems.append(f"穿线风暴: 拒错缺 retry_after: {counter}")
    third = json.loads(mailbox_mcp.do_send(ALICE, "pi-node-9-third", "回函: 第三腿OK"))
    if not third.get("ok"):
        problems.append(f"穿线风暴: 无关对被对称限速误伤: {third}")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
