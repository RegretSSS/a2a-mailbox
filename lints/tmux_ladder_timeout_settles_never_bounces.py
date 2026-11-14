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
    injects = {"n": 0}
    real_prime = hub.tmuxio.prime_injection
    real_quiet = hub.tmuxio.quiet_mark
    hub.tmuxio.quiet_mark = lambda pane, ssh_host=None: "0"
    delivery.tick(root, SilentLog(), 102.0, True, None)
    hub.tmuxio.prime_injection = lambda *a, **k: injects.__setitem__("n", injects["n"] + 1)
    clock = {"t": 0, "churn": True}
    original_capture = hub.tmuxio.capture_joined_bottom

    def churning_then_pending(pane, line_count=60, ssh_host=None):
        if clock["churn"]:
            clock["t"] += 1
            return "\n".join(
                [f"history line {n}" for n in range(20)]
                + ["input box"] * 8
                + ["", "queued [A2A] from=sender-a id=tm0000000001 rest" + "·" * clock["t"]]
            )
        return "\n".join(
            [f"history line {n}" for n in range(20)]
            + ["input box"] * 8
            + ["", "queued [A2A] from=sender-a id=tm0000000001 rest of text"]
        )

    log = SilentLog()
    hub.tmuxio.capture_joined_bottom = churning_then_pending
    try:
        frames: dict = {}
        for moment in (103.0, 110.0, 150.0, 200.0):
            frames.clear()
            delivery.tick(root, log, moment, True, frames)
        if delivery.state != hub.STATE_INJECTING:
            problems.append(f"尾区驻留: churn 卡 ladder 期应保持 INJECTING, 实际 {delivery.state}")
        clock["churn"] = False
        frames.clear()
        delivery.tick(root, log, 201.0, True, frames)
        if delivery.state != hub.STATE_WAIT_CONFIRM:
            problems.append(
                f"尾区驻留: patience 到期+文本驻留输入区应 settle 进 WAIT_CONFIRM, 实际 {delivery.state}——"
                "实测 68293e5995ed 三信 2026-11-12 被 injection ladder timeout 假 FAILED+假回弹, "
                "而文本早已注入 %5 排队区等待消费"
            )
        if any("FAILED" in line or "bounce" in line for line in log.lines):
            problems.append("尾区驻留: settle 路径出现 FAILED/bounce——按铃尽力一次, 消费与否归收件方")
        if not any("via=tail-echo" in line for line in log.lines):
            problems.append("尾区驻留: settle 未记录 via=tail-echo 送达形态(文本可见即已注入)")
        delivery.tick(root, log, 201.0 + hub.CONFIRM_PATIENCE_SECONDS + 10.0, True, frames)
        if delivery.state != hub.STATE_DONE:
            problems.append("尾区驻留: CONFIRM_PATIENCE 后应以 unconfirmed 归档收尾")
        if (root / "queue" / "busy-b" / "tm0000000001.failed").exists():
            problems.append("尾区驻留: 通知类未确认信竟落 .failed——应 archive 而非留失败痕")
        if injects["n"] != 0:
            problems.append(f"尾区驻留: 竟然重注 {injects['n']} 次——上轮字符尚在输入区, 重注=收件方重复消费")
    finally:
        hub.tmuxio.prime_injection = real_prime
        hub.tmuxio.quiet_mark = real_quiet
        hub.tmuxio.capture_joined_bottom = original_capture
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
