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


def build(root: Path, now: float):
    from common import storage
    from hub.hub import Delivery

    envelope = {
        "msg_id": "ea0000000001",
        "ack_id": "ack-ea0000000001",
        "from": "claude-host-a-a2a-mailbox",
        "to": "pi-host-a-a2a-mailbox",
        "body": "任务: 读 DESIGN.md 并回函",
        "wake_text": "[A2A] from=claude-host-a-a2a-mailbox id=ea0000000001 ack=ack-ea0000000001\n任务: 读 DESIGN.md 并回函\n[需回函]",
    }
    storage.enqueue(root, envelope)
    delivery = Delivery(envelope, now, pane_id="%7")
    delivery.round_index = 1
    delivery.injected_at = now - 40.0
    delivery.state = "BACKOFF"
    delivery.state_since = now - 9.0
    delivery.echo_baseline_count = 0
    return storage, delivery


def lint() -> list[str]:
    problems = []
    workspace = tempfile.mkdtemp(prefix="a2a-lint-")
    os.environ["A2A_MAILBOX_ROOT"] = workspace
    root = Path(workspace)
    from hub import hub

    storage, delivery = build(root, time.time())
    log = SilentLog()
    echo_hits = {"count": 0}
    original_capture = hub.tmuxio.capture_joined_bottom

    def capture_with_echo(pane_id, line_count=60, ssh_host=None):
        echo_hits["count"] += 1
        filler = "\n".join(f"pad {n}" for n in range(12))
        return "[A2A] id=ea0000000001 任务: 读 DESIGN.md 并回函 [需回函]\n" + filler + "\ninput empty"

    hub.tmuxio.capture_joined_bottom = capture_with_echo
    try:
        delivery.tick(root, log, time.time(), True)
    finally:
        hub.tmuxio.capture_joined_bottom = original_capture
    joined = "\n".join(log.lines)
    if "receipt ea0000000001" not in joined or "late" not in joined:
        problems.append(f"echo 迟到: BACKOFF 中 echo 已回显应记 receipt(late) 而非重投——log: {log.lines}")
    if "injected" in joined:
        problems.append(f"echo 迟到: echo 已回显仍重投(重复注入骚扰)——log: {log.lines}")
    if delivery.state != "WAIT_CONFIRM":
        problems.append(f"echo 迟到: receipt 后应转 WAIT_CONFIRM, 实际 {delivery.state}")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
