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

    envelope = {"msg_id": "tm0000000001", "ack_id": "ack-tm0000000001", "from": "sender-a",
                "to": "busy-b", "body": "x", "created_at": 1.0,
                "wake_text": "wake tm0000000001"}
    storage.enqueue(root, envelope)
    delivery = hub.Delivery(envelope, now=100.0, pane_id="%7")
    delivery.state = hub.STATE_WAIT_ECHO
    delivery.injected_at = 100.0
    delivery.echo_deadline = 100.0 + hub.ECHO_TIMEOUT_SECONDS
    delivery.enter_tail = ""
    injects = {"n": 0}
    real_prime = hub.tmuxio.prime_injection
    hub.tmuxio.prime_injection = lambda *a, **k: injects.__setitem__("n", injects["n"] + 1)
    try:
        pending_frame = "\n".join(
            [f"history line {n}" for n in range(20)]
            + ["input box"] * 9
            + ["queued [A2A] from=sender-a id=tm0000000001 rest"]
        )
        frames = {"": {"%7": pending_frame}}
        past_patience = 100.0 + hub.ECHO_PATIENCE_SECONDS + 1.0
        log = SilentLog()
        delivery.tick(root, log, past_patience, True, frames)
        if delivery.state == hub.STATE_FAILED:
            problems.append(
                "尾区驻留: 注入文本挂在收件方输入区(busy 排队)被误判 echo timeout——"
                "实测 571ef3000687 三轮重注后假 FAILED+假回弹, 而消息实际送达 3 次"
            )
        if any("bounce" in line for line in log.lines):
            problems.append("尾区驻留: 假失败触发回弹, 骚扰发送方(实已达)")
        hold_deadline = past_patience + hub.TAIL_HOLD_TIMEOUT_SECONDS + 1.0
        delivery.tick(root, log, hold_deadline, True, frames)
        if delivery.state != hub.STATE_WAIT_CONFIRM:
            problems.append("尾区驻留: hold 超时未转 WAIT_CONFIRM(字符可见即回显成立, 应等 ack/收尾)")
        if injects["n"] != 0:
            problems.append(f"尾区驻留: 竟然重注 {injects['n']} 次——上轮字符尚在输入区, 重注=收件方重复消费")
    finally:
        hub.tmuxio.prime_injection = real_prime
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
