#!/usr/bin/env python3
import os
import sys
import tempfile
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
    from common import msgfmt, storage
    from hub import hub

    storage.enqueue(root, {"msg_id": "iz0000000001", "ack_id": "ack-iz0000000001", "from": "a", "to": BOB, "body": "x", "created_at": 1.0,
                           "wake_text": msgfmt.compose_wake("a", "iz0000000001", "x")})
    envelope = {"msg_id": "iz0000000001", "ack_id": "ack-iz0000000001", "from": "a", "to": BOB,
                "body": "x", "wake_text": msgfmt.compose_wake("a", "iz0000000001", "x")}
    delivery = hub.Delivery(envelope, now=100.0, pane_id="%7")
    frames_mode = {"history": "draft"}
    original_capture = hub.tmuxio.capture_joined_bottom

    def zone_capture(pane, line_count=60, ssh_host=None):
        filler = "\n".join(f"pad {n}" for n in range(12))
        if frames_mode["history"] == "submitted":
            return "\n".join(["[A2A] id=iz0000000001 已提交历史区", filler, "input box empty"])
        if frames_mode["history"] == "history_with_draft":
            return "\n".join(["[A2A] id=iz0000000001 已提交历史区", filler, "draft [A2A] id=iz0000000001 在输入框"])
        return "\n".join(["history line", filler, "[A2A] id=iz0000000001 在输入框未提交"])

    hub.tmuxio.capture_joined_bottom = zone_capture
    try:
        delivery.baseline_echo(100.0)
        frames = {}
        hub.tmuxio.capture_joined_bottom = zone_capture
        if delivery.echo_arrived(frames):
            problems.append("echo 历史区: 草稿在输入框未提交却判定回显——判定未排除输入区")
        frames_mode["history"] = "history_with_draft"
        frames.clear()
        if delivery.echo_arrived(frames):
            problems.append("echo 历史区: 历史区已出现但草稿仍在输入框——双条件失效会假 receipt 短路补 Enter")
        frames_mode["history"] = "submitted"
        frames.clear()
        if not delivery.echo_arrived(frames):
            problems.append("echo 历史区: 消息已进历史区且输入框已清空却判不命中——真实提交被漏判")
    finally:
        hub.tmuxio.capture_joined_bottom = original_capture
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
