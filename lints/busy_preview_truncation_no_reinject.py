#!/usr/bin/env python3
import os
import sys
import tempfile
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
    from common import storage
    from hub import hub

    if hub.DELIVER_BACKOFF_SECONDS[1] < 45.0 or hub.DELIVER_BACKOFF_SECONDS[2] < 120.0:
        problems.append(
            f"双重发送: BACKOFF 间隔 {hub.DELIVER_BACKOFF_SECONDS} 过急——busy 收件方 pending 消费分钟级, "
            "实测 aa5fddacca52 在 31s 重注致 Backend 双份"
        )

    envelope = {"msg_id": "ds0000000001", "ack_id": "ack-ds0000000001", "from": "sender-a",
                "to": "busy-b", "body": "x", "created_at": 1.0,
                "wake_text": "[A2A] from=sender-a id=ds0000000001\nx"}
    storage.enqueue(root, envelope)
    delivery = hub.Delivery(envelope, now=100.0, pane_id="%8")
    delivery.state = hub.STATE_BACKOFF
    delivery.state_since = 100.0
    delivery.injected_at = 100.0
    delivery.round_index = 1
    delivery.echo_deadline = 100.0 + hub.ECHO_TIMEOUT_SECONDS
    preview_frame = "\n".join(
        [f"history line {n}" for n in range(20)] + ["input box"] * 9 + ["» [A2A] from=sender-a id=ds0000…"]
    )
    frames = {"": {"%8": preview_frame}}
    injects = {"n": 0}
    real_prime = hub.tmuxio.prime_injection
    hub.tmuxio.prime_injection = lambda *a, **k: injects.__setitem__("n", injects["n"] + 1)
    try:
        tail = delivery.tail_zone(frames)
        if "ds0000000001" in tail and delivery.wake_head() not in tail:
            problems.append("双重发送: 构造失效——preview 帧应含截断头行而非完整 msg_id")
        if not delivery.marker_in_tail(frames):
            problems.append("双重发送: preview 截断(msg_id 不可见但 wake 头行前缀可见)未被识别为已接收——本案 aa5fdd 形态会重注")
        for moment in (100.0 + hub.DELIVER_BACKOFF_SECONDS[1] - 5.0, 100.0 + hub.DELIVER_BACKOFF_SECONDS[1] - 1.0):
            delivery.tick(root, SilentLog(), moment, True, frames)
            if injects["n"] != 0:
                problems.append("双重发送: 退避窗内对 preview 驻留消息重注——收件方将重复消费")
                break
    finally:
        hub.tmuxio.prime_injection = real_prime
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
