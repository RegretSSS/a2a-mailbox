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

    envelope = {"msg_id": "cg0000000001", "ack_id": "ack-cg0000000001", "from": "a", "to": "b",
                "body": "x", "created_at": 1.0, "wake_text": "wake cg0000000001"}
    storage.enqueue(root, envelope)
    delivery = hub.Delivery(envelope, now=100.0, pane_id="%7")
    delivery.state = hub.STATE_WAIT_ECHO
    delivery.injected_at = 100.0
    delivery.echo_deadline = 100.0 + hub.ECHO_TIMEOUT_SECONDS
    delivery.enter_tail = "x" * 40
    churn_frames = {"": {"%7": "\n".join(["pad line"] * 10 + ["x" * n for n in (45, 50, 55, 60, 65, 70)])}}
    past_window = 100.0 + hub.ECHO_TIMEOUT_SECONDS + 3.0
    delivery.tick(root, SilentLog(), past_window, True, churn_frames)
    if delivery.state != hub.STATE_WAIT_ECHO:
        problems.append(
            "churn 延展: pane 在动却跨过 echo 窗转 BACKOFF——实测 echo 分布 27-52s, 纯 15s 窗会确定性重复注入"
        )
    beyond_patience = 100.0 + hub.ECHO_PATIENCE_SECONDS + 1.0
    delivery.tick(root, SilentLog(), beyond_patience, True, churn_frames)
    if delivery.state != hub.STATE_FAILED:
        problems.append("churn 延展: 缺总 patience 上限——churn 无界延展会永久滞留 WAIT_ECHO")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
