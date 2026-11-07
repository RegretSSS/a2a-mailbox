#!/usr/bin/env python3
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
BOB = "pi-host-a-a2a-mailbox"


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
    from common import registry, storage
    from hub import hub

    registry.upsert(root, BOB, {"cli": "pi", "pane_id": "%7", "pane_pid": "1", "slot": "pi:pi-r"})
    from common import nativebox

    nativebox.write_alive(root, BOB, 4321, time.time())
    envelope = {
        "msg_id": "hr0000000001",
        "ack_id": "ack-hr0000000001",
        "from": "claude-host-a-a2a-mailbox",
        "to": BOB,
        "body": "任务: 读 DESIGN.md 并回函",
        "last_injected_at": time.time() - 300.0,
    }
    storage.enqueue(root, envelope)
    inject_calls = {"count": 0}
    original_inject = hub.tmuxio.inject_wake
    original_capture = hub.tmuxio.capture_joined_bottom

    def no_inject(pane_id, text, ssh_host=None):
        inject_calls["count"] += 1

    def no_capture(pane_id, line_count=60, ssh_host=None):
        return ""

    hub.tmuxio.inject_wake = no_inject
    hub.tmuxio.capture_joined_bottom = no_capture
    try:
        reg = {"agents": {BOB: registry.get(root, BOB)}}
        log = SilentLog()
        now = time.time()
        hub.step(root, reg, {}, log, now, {BOB: True})
        key = f"{BOB}/hr0000000001"
        probe = {}
        hub.step(root, reg, probe, log, time.time() + 1.0, {BOB: True})
        delivery = probe.get(key)
        if inject_calls["count"]:
            problems.append(
                f"hub 重启: 已注入未确认消息被重投 {inject_calls['count']} 次——"
                "last_injected_at 早于 guard 窗口时应恢复 WAIT_CONFIRM 等 ack/patience, 不是重新注入"
            )
        if delivery is None:
            problems.append("hub 重启: 已注入消息未重建 Delivery（ack 到达时将无法 confirm）")
        elif delivery.state != "WAIT_NATIVE":
            problems.append(f"hub 重启: 已注入无 rcpt 的 pi 档应恢复 WAIT_NATIVE 续等扩展回执, 实际 {delivery.state}")
        elif delivery.state_since != envelope["last_injected_at"]:
            problems.append("hub 重启: patience 应从原注入时刻起算, 不从重建时刻重置")
        elif not delivery.native:
            problems.append("hub 重启: pi 恢复态必须保持 native 通道——降级 pane 注入会与扩展消费双轨竞争")
    finally:
        hub.tmuxio.inject_wake = original_inject
        hub.tmuxio.capture_joined_bottom = original_capture
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
