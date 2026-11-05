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
LEG_BODIES = (
    ("E2E-V2 pi 腿回函OK", "pi"),
    ("E2E-V2 codex-wsl 腿回函OK", "codex-wsl"),
)


def prepare():
    workspace = tempfile.mkdtemp(prefix="a2a-lint-")
    os.environ["A2A_MAILBOX_ROOT"] = workspace
    os.environ["A2A_HOST_TAG"] = "lint"
    sys.path.insert(0, str(ROOT))
    from common import registry, storage
    spec = importlib.util.spec_from_file_location("mailbox_mcp", ROOT / "mcp" / "mailbox_mcp.py")
    mailbox_mcp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mailbox_mcp)
    root = Path(workspace)
    for agent_id in (ALICE, BOB):
        registry.upsert(root, agent_id, {"cli": "codex", "pane_id": "%1", "pane_pid": "1"})
    return mailbox_mcp, storage, root


def lint() -> list[str]:
    problems = []
    mailbox_mcp, storage, root = prepare()
    for body, leg in LEG_BODIES:
        sent = json.loads(mailbox_mcp.do_send(ALICE, BOB, f"任务: 读 DESIGN.md『E2E-V2』; {leg} 腿"))
        if not sent.get("ok"):
            problems.append(f"回函回归({leg}): 原始任务消息发送失败 {sent}")
            continue
        reply = json.loads(mailbox_mcp.do_send(BOB, ALICE, body, in_reply_to=sent["msg_id"]))
        if not reply.get("ok"):
            problems.append(
                f"回函回归({leg}): ack 后首次回函被拒——『{body}』应凭有效 in_reply_to 一次通过: {reply}"
            )
        elif not storage.ack_exists(root, storage.find_msg(root, sent["msg_id"])["ack_id"]):
            problems.append(f"回函回归({leg}): reply-implies-ack 未落原消息确认")
    null_reply = json.loads(mailbox_mcp.do_send(BOB, ALICE, LEG_BODIES[0][0], in_reply_to="null"))
    if not null_reply.get("ok"):
        problems.append(f"回函回归: in_reply_to='null' 应归一化为缺失直接发送: {null_reply}")
    bare = json.loads(mailbox_mcp.do_send(BOB, ALICE, LEG_BODIES[1][0]))
    if not bare.get("ok"):
        problems.append(f"回函回归: 短回执无 in_reply_to 应免线索一次通过: {bare}")
    stale = json.loads(mailbox_mcp.do_send(BOB, ALICE, LEG_BODIES[0][0], in_reply_to="deadbeefcafe"))
    if stale.get("ok") or "mail_read" not in str(stale.get("error")):
        problems.append(f"回函回归: 未知 in_reply_to 应拒绝且报错附示例: {stale}")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
