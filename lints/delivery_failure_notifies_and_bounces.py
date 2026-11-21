#!/usr/bin/env python3
import json
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


class RecordingPool:
    def __init__(self):
        self.spawned = []

    def spawn(self, cmd, payload, event, log):
        self.spawned.append((cmd, payload, event))

    def reap(self, log, now):
        pass


def lint() -> list[str]:
    problems = []
    workspace = tempfile.mkdtemp(prefix="a2a-lint-")
    os.environ["A2A_MAILBOX_ROOT"] = workspace
    root = Path(workspace)
    from common import msgfmt, storage
    from hub import hub

    storage.enqueue(root, {"msg_id": "nf0000000001", "ack_id": "ack-nf0000000001", "from": SENDER, "to": BOB,
                           "body": "x", "created_at": 1.0,
                           "wake_text": msgfmt.compose_wake(SENDER, "nf0000000001", "x")})
    reg = {"agents": {BOB: {"agent_id": BOB, "cli": "codex", "host": "localhost", "pane_id": "", "pane_pid": ""}}}
    pool = RecordingPool()
    original_pool = hub.NOTIFY_POOL
    original_cmd = hub.load_notify_cmd
    hub.NOTIFY_POOL = pool
    hub.load_notify_cmd = lambda log=None: ["toast"]
    try:
        hub.step(root, reg, {}, SilentLog(), 100.0, {BOB: True})
        events = [json.loads(payload) for _, payload, _ in pool.spawned]
        delivery_failed = [item for item in events if item.get("event") == "delivery-failed"]
        if not delivery_failed or "no delivery path" not in str(delivery_failed[0].get("reason")):
            problems.append(f"投递失败: no-delivery-path 必须统一 notify delivery-failed(带 reason)——原版根本不调: {events}")
        bounced = storage.list_queue(root, SENDER)
        if not bounced:
            problems.append("投递失败: 必须回弹 envelope 回发送方——失败只在 hub.log 可见时发送方 agent 无感知")
        elif bounced[0].get("in_reply_to") != "nf0000000001" or bounced[0].get("bounce") is not True:
            problems.append(f"投递失败: 回弹信封缺原 msg_id 锚/防递归标记: {bounced[0]}")
        doomed = {"msg_id": "nf0000000002", "ack_id": "ack-nf0000000002", "from": hub.HUB_FROM, "to": BOB,
                  "body": "x", "created_at": 1.0, "bounce": True,
                  "wake_text": msgfmt.compose_wake(hub.HUB_FROM, "nf0000000002", "x")}
        storage.enqueue(root, doomed)
        hub.step(root, reg, {}, SilentLog(), 102.0, {BOB: True})
        rebound = storage.list_queue(root, hub.HUB_FROM)
        if rebound:
            problems.append("投递失败: 回弹自身的失败不得再回弹——防递归守卫失效")
    finally:
        hub.NOTIFY_POOL = original_pool
        hub.load_notify_cmd = original_cmd
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
