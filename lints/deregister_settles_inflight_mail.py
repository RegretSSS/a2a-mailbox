#!/usr/bin/env python3
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
BOB = "pi-host-a-a2a-mailbox"
SENDER = "claude-host-a-a2a-mailbox"


class SilentLog:
    def __init__(self):
        self.lines = []

    def write(self, line):
        self.lines.append(line)


def lint() -> list[str]:
    problems = []
    workspace = tempfile.mkdtemp(prefix="a2a-lint-")
    os.environ["A2A_MAILBOX_ROOT"] = workspace
    root = Path(workspace)
    from common import msgfmt, registry, storage
    from hub import hub

    storage.enqueue(root, {"msg_id": "ds0000000001", "ack_id": "ack-ds0000000001", "from": SENDER, "to": BOB,
                           "body": "x", "created_at": 1.0,
                           "wake_text": msgfmt.compose_wake(SENDER, "ds0000000001", "x")})
    reg = {"agents": {BOB: {"agent_id": BOB, "cli": "codex", "host": "localhost", "pane_id": "%7", "pane_pid": "7"}}}
    deliveries = {f"{BOB}/ds0000000001": hub.Delivery(
        {"msg_id": "ds0000000001", "ack_id": "ack-ds0000000001", "from": SENDER, "to": BOB,
         "body": "x", "wake_text": "w"}, now=100.0, pane_id="%7")}

    pruned = hub.prune_registry(reg, root, SilentLog(), {BOB: False}, 100.0, None, deliveries)

    if pruned != [BOB]:
        problems.append(f"注销善后: 死 pane 记录应被注销: {pruned}")
    if not (storage.queue_dir(root, BOB) / "ds0000000001.failed").exists():
        problems.append("注销善后: 队列邮件未 mark_failed——注销后随目录变孤儿, 发送方永远等不到回音")
    if not storage.list_queue(root, SENDER):
        problems.append("注销善后: 未回弹发送方——recipient deregistered 也必须闭环反馈")
    if deliveries:
        problems.append("注销善后: 在途 delivery 未清——offline 目标永久停摆且钉死 1s 活跃 tick")

    ghost = {"msg_id": "ds0000000002", "ack_id": "ack-ds0000000002", "from": SENDER, "to": "ghost-9",
             "body": "x", "created_at": 1.0,
             "wake_text": msgfmt.compose_wake(SENDER, "ds0000000002", "x")}
    storage.enqueue(root, ghost)
    registry.upsert(root, SENDER, {"cli": "claude", "pane_id": "%3", "pane_pid": "3"})
    swept = hub.sweep_orphan_queues(root, SilentLog(), {"agents": {}})
    if "ghost-9" not in swept:
        problems.append(f"注销善后: 孤儿队列目录应被一次性 sweep 处置: {swept}")
    if SENDER in swept:
        problems.append("注销善后: 孤儿 sweep 未重查磁盘注册表——已注册 agent 的队列被误处置")
    registry.upsert(root, "racer-9", {"cli": "codex", "pane_id": "%5"})
    racer = dict(ghost)
    racer.update({"msg_id": "ds0000000003", "to": "racer-9"})
    storage.enqueue(root, racer)
    survived = hub.sweep_orphan_queues(root, SilentLog(), {"agents": {}})
    if "racer-9" in survived or not storage.list_queue(root, "racer-9"):
        problems.append("注销善后: 孤儿 sweep 必须重查注册表——respawn 竞态会误杀刚重注册的 agent")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
