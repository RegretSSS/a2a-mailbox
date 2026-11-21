#!/usr/bin/env python3
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


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
    from common import msgfmt, nativebox, paths, storage
    from hub import hub

    paths.ensure_layout(root)
    envelope = {
        "msg_id": "na0000000001",
        "ack_id": "ack-na0000000001",
        "from": "sender-h",
        "to": "pi-worker",
        "body": "pi 原生通道 lint: 确定性入队不得触发 tmux 注入",
        "created_at": 1.0,
        "wake_text": msgfmt.compose_wake("sender-h", "na0000000001", "pi 原生通道 lint: 确定性入队不得触发 tmux 注入"),
    }
    storage.enqueue(root, envelope)
    record = {
        "agent_id": "pi-worker",
        "cli": "pi",
        "host": "localhost",
        "pane_id": "%9",
        "pane_pid": "900",
        "cwd": "/tmp",
        "spawn_cmd": None,
    }
    injects = {"n": 0}
    real_prime = hub.tmuxio.prime_injection
    hub.tmuxio.prime_injection = lambda *a, **k: injects.__setitem__("n", injects["n"] + 1)
    real_created = hub.tmuxio.pane_created
    hub.tmuxio.pane_created = lambda pane, ssh=None: 0.0
    log = SilentLog()
    try:
        start = time.time()
        nativebox.write_alive(root, "pi-worker", 777, start)
        delivery = hub.build_delivery(envelope, record, start, root)
        if delivery is None or not delivery.native:
            problems.append("pi 原生投递: cli=pi 且 alive 新鲜时必须建 native 投递, 否则退回帧面推断链路")
            return problems
        delivery.dispatch_native(root, log, start)
        if delivery.state != hub.STATE_WAIT_CONFIRM:
            problems.append("pi 原生投递: dispatch 即送达——写队列为确定性动作, 应直接 WAIT_CONFIRM 等 ack")
        if float(storage.read_msg(root, "pi-worker", "na0000000001").get("last_injected_at") or 0) != start:
            problems.append("pi 原生投递: dispatch 未 stamp last_injected_at, hub 重启将重 dispatch")

        silent = start + 90.0
        delivery.tick(root, log, silent, True, None)
        if delivery.state != hub.STATE_WAIT_CONFIRM or not delivery.native:
            problems.append("pi 原生投递: 扩展回执缺席/心跳过期都不得降级 tmux——队列文件已是邮箱, 消费节奏归收件方")

        nativebox.write_rcpt(root, "pi-worker", "na0000000001", start + 3.0)
        delivery.tick(root, log, silent + 1.0, True, None)
        if delivery.state != hub.STATE_WAIT_CONFIRM:
            problems.append("pi 原生投递: rcpt 只是消费痕迹, 到达时也已在该状态——不得改变投递状态机")

        storage.write_ack(root, "ack-na0000000001", "pi-worker")
        delivery.tick(root, log, silent + 2.0, True, None)
        if delivery.state != hub.STATE_DONE:
            problems.append("pi 原生投递: ack 到达必须 DONE")
        if injects["n"] != 0:
            problems.append("pi 原生投递: 全链 dispatch→rcpt→ack 不允许任何 tmux 注入——确定性通道的意义就是短路帧面推断")
    finally:
        hub.tmuxio.prime_injection = real_prime
        hub.tmuxio.pane_created = real_created
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
