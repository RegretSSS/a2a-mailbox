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


def build_delivery(hub):
    envelope = {"msg_id": "al0000000001", "ack_id": "ack-al0000000001", "from": "sender-a",
                "to": "busy-b", "body": "任务收到, 处理中给结论", "created_at": 1.0,
                "wake_text": "[A2A] from=sender-a id=al0000000001\n任务收到, 处理中给结论\n[需回函]"}
    delivery = hub.Delivery(envelope, now=100.0, pane_id="%8")
    delivery.state = hub.STATE_BACKOFF
    delivery.state_since = 100.0
    delivery.injected_at = 100.0
    delivery.round_index = 1
    delivery.echo_deadline = 100.0 + hub.ECHO_TIMEOUT_SECONDS
    return delivery


def spinner_frames(clock, base=100.0):
    clock["t"] += 1
    frame = "\n".join(
        [f"history line {n}" for n in range(20)]
        + ["input box"] * 2
        + [f"✻ Gitifying… (3m {clock['t']}s · ↓ 11.9k tokens)", "", "─" * 30, "❯"]
    )
    return {"": {"%8": frame}}


def lint() -> list[str]:
    problems = []
    workspace = tempfile.mkdtemp(prefix="a2a-lint-")
    os.environ["A2A_MAILBOX_ROOT"] = workspace
    root = Path(workspace)
    from common import storage
    from hub import hub

    envelope = build_delivery(hub).envelope
    storage.enqueue(root, envelope)
    injects = {"n": 0}
    real_prime = hub.tmuxio.prime_injection
    hub.tmuxio.prime_injection = lambda *a, **k: injects.__setitem__("n", injects["n"] + 1)
    clock = {"t": 0}
    try:
        delivery = build_delivery(hub)
        moment = 100.0
        while moment + 60.0 < 100.0 + hub.ABSOLUTE_PATIENCE_SECONDS:
            moment += 60.0
            delivery.tick(root, SilentLog(), moment, True, spinner_frames(clock))
            if delivery.state == hub.STATE_FAILED or injects["n"] != 0:
                problems.append(
                    "存活重注: 收件 CLI 帧持续变化(spinner/渲染)期间重注或判死——"
                    "实测 c820b229124d 三轮重注+假 FAILED 时消息正在上屏(dump 铁证)"
                )
                break
        if delivery.state == hub.STATE_BACKOFF:
            delivery.tick(root, SilentLog(), 100.0 + hub.ABSOLUTE_PATIENCE_SECONDS + 60.0, True, spinner_frames(clock))
            if delivery.state != hub.STATE_FAILED:
                problems.append("存活重注: 绝对上限失效——CLI 活跃但消息永不上屏时必须能 fail 回弹, 否则发送方无知情")
            if injects["n"] != 0:
                problems.append("存活重注: 绝对上限以重注收场——活跃期重注即制造重复消费")
    finally:
        hub.tmuxio.prime_injection = real_prime
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
