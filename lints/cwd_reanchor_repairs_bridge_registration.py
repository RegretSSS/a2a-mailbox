#!/usr/bin/env python3
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

GHOST = "unknown-h-9-ghost"


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

    registry.upsert(root, GHOST, {"agent_id": GHOST, "cli": "codex", "host": "localhost",
                                  "pane_id": "", "pane_pid": "", "slot": "", "cwd": "/mnt/d/000-project",
                                  "spawn_cmd": None})
    storage.enqueue(root, {"msg_id": "ra0000000001", "ack_id": "ack-ra0000000001", "from": "sender-a",
                           "to": GHOST, "body": "回函已收到核对", "hop": 1, "created_at": 1.0,
                           "wake_text": "wake ra0000000001"})
    snapshots = {"": {"panes": {
        "%9": {"pane_pid": "999", "slot": "zero:codexmaster", "pane_created": "0", "cwd": "/mnt/d/000-project",
               "command": "codex"},
    }, "slots": {}}}
    log = SilentLog()
    reg = registry.load(root)
    hub.reanchor_cwd_panes(reg, root, log, snapshots)
    if registry.load(root)["agents"][GHOST].get("pane_id") != "%9":
        return ["cwd 回锚: wsl.exe 桥注册(无 TMUX_PANE)的记录未按 cwd 匹配补锚——host-b codex 主控实测黑洞形态"]

    injects = {"n": 0}
    real_prime = hub.tmuxio.prime_injection
    hub.tmuxio.prime_injection = lambda *a, **k: injects.__setitem__("n", injects["n"] + 1)
    hub.tmuxio.pane_created = lambda pane, ssh_host=None: 0.0
    hub.tmuxio.quiet_mark = lambda pane, ssh_host=None: "0"
    try:
        deliveries: dict = {}
        hub.step(root, registry.load(root), deliveries, log, 500.0, {GHOST: True})
        hub.step(root, registry.load(root), deliveries, log, 502.0, {GHOST: True})
        delivery = deliveries.get(f"{GHOST}/ra0000000001")
        if delivery is None or injects["n"] == 0:
            problems.append("cwd 回锚: 补锚后滞留消息未被接管投递——回锚必须打通收信, 否则只是换一种滞留")
    finally:
        hub.tmuxio.prime_injection = real_prime
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
