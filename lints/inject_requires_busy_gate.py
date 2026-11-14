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

    storage.enqueue(root, {"msg_id": "bg0000000001", "ack_id": "ack-bg0000000001", "from": "a", "to": BOB,
                           "body": "x", "created_at": 1.0,
                           "wake_text": msgfmt.compose_wake("a", "bg0000000001", "x")})
    reg = {"agents": {BOB: {"agent_id": BOB, "cli": "codex", "pane_id": "%7", "pane_pid": "7"}}}
    probes = {"busy": True, "injects": 0}

    original_busy_frame = hub.tmuxio.busy_probe_frame
    original_grew = hub.tmuxio.frame_grew_since
    original_quiet = hub.tmuxio.quiet_mark
    original_prime = hub.tmuxio.prime_injection
    original_created = hub.tmuxio.pane_created

    def frame_recorder(pane, ssh_host=None):
        return "frame-a"

    def grew_probe(first, pane, ssh_host=None):
        return probes["busy"]

    def prime_recorder(pane, wake_text, ssh_host=None):
        probes["injects"] += 1

    hub.tmuxio.busy_probe_frame = frame_recorder
    hub.tmuxio.frame_grew_since = grew_probe
    hub.tmuxio.quiet_mark = lambda pane, ssh_host=None: ""
    hub.tmuxio.prime_injection = prime_recorder
    hub.tmuxio.pane_created = lambda pane, ssh_host=None: 0.0
    try:
        deliveries = {}
        hub.step(root, reg, deliveries, SilentLog(), 100.0, {BOB: True})
        hub.step(root, reg, deliveries, SilentLog(), 102.0, {BOB: True})
        if probes["injects"]:
            problems.append("busy 闸门: pane 占用时仍注入——未提交草稿会被 1200 BSpace 清掉, 裸注入是时序破坏源")
        if not deliveries:
            problems.append("busy 闸门: 占用退让应保留 delivery(SETTLING)而不是丢弃")
        hub.step(root, reg, deliveries, SilentLog(), 102.5, {BOB: True})
        if probes["busy"] and probes["injects"]:
            problems.append("busy 闸门: 两相探测第二相判定占用仍注入")
        probes["busy"] = False
        hub.step(root, reg, deliveries, SilentLog(), 103.0, {BOB: True})
        hub.step(root, reg, deliveries, SilentLog(), 104.0, {BOB: True})
        if probes["injects"] != 1:
            problems.append("busy 闸门: pane 空闲后应放行注入一次")
    finally:
        hub.tmuxio.busy_probe_frame = original_busy_frame
        hub.tmuxio.frame_grew_since = original_grew
        hub.tmuxio.quiet_mark = original_quiet
        hub.tmuxio.prime_injection = original_prime
        hub.tmuxio.pane_created = original_created
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
