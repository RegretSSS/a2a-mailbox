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

    storage.enqueue(root, {"msg_id": "pl0000000001", "ack_id": "ack-pl0000000001", "from": "a", "to": BOB,
                           "body": "x", "created_at": 1.0,
                           "wake_text": msgfmt.compose_wake("a", "pl0000000001", "x")})
    reg = {"agents": {BOB: {"agent_id": BOB, "cli": "codex", "pane_id": "%7", "pane_pid": "7"}}}
    probes = {"prime": 0, "wake": 0, "enter": 0}
    original = {name: getattr(hub.tmuxio, name, None) for name in
                ("prime_injection", "send_enter", "quiet_mark", "busy_probe_frame", "frame_grew_since", "pane_created",
                 "capture_joined_bottom")}
    static_frame = "\n".join(["history line"] * 20 + ["input box"])

    def prime_recorder(pane, wake_text, ssh_host=None):
        probes["prime"] += 1

    def wake_recorder(pane, wake_text, ssh_host=None):
        probes["wake"] += 1

    def enter_recorder(pane, ssh_host=None):
        probes["enter"] += 1

    hub.tmuxio.prime_injection = prime_recorder
    hub.tmuxio.inject_wake = wake_recorder
    hub.tmuxio.send_enter = enter_recorder
    hub.tmuxio.quiet_mark = lambda pane, ssh_host=None: "0"
    hub.tmuxio.busy_probe_frame = lambda pane, ssh_host=None: "frame-a"
    hub.tmuxio.frame_grew_since = lambda first, pane, ssh_host=None: False
    hub.tmuxio.pane_created = lambda pane, ssh_host=None: 0.0
    hub.tmuxio.capture_joined_bottom = lambda pane, line_count=60, ssh_host=None: static_frame
    try:
        deliveries = {}
        hub.step(root, reg, deliveries, SilentLog(), 100.0, {BOB: True})
        hub.step(root, reg, deliveries, SilentLog(), 102.0, {BOB: True})
        key = f"{BOB}/pl0000000001"
        if probes["wake"]:
            problems.append("注入阶梯: 走了盲睡 inject_wake(11.1s 固定地板)——必须 prime_injection+INJECTING 探测阶梯")
        if probes["prime"] != 1:
            problems.append(f"注入阶梯: prime_injection 调用 {probes['prime']} 次, 应恰好 1 次")
        delivery = deliveries.get(key)
        if delivery is None or delivery.state != hub.STATE_INJECTING:
            problems.append("注入阶梯: 注入后必须进 STATE_INJECTING 由 churn/静止阶梯接管 Enter")
        churn_frames = {"": {"%7": "\n".join(["pad line"] * 10 + ["x" * n for n in (45, 50, 55, 60, 65, 70)])}}
        delivery.enter_tail = "x" * 40
        delivery.enter_deadline = 103.0
        delivery.tick(root, SilentLog(), 104.0, True, churn_frames)
        if probes["enter"]:
            problems.append("注入阶梯: pane 在动仍补 Enter——churn 必须阻止升档, 否则流式输出被截断")
    finally:
        for name, fn in original.items():
            if fn is not None:
                setattr(hub.tmuxio, name, fn)
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
