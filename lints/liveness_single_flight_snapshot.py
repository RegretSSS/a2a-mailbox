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
    from common import registry
    from hub import hub

    record = {
        "cli": "pi",
        "pane_id": "%7",
        "pane_pid": "1",
        "slot": "pi:pi-r",
        "agent_id": BOB,
    }
    registry.upsert(root, BOB, record)
    calls = {"slot_pane_id": 0, "pane_pid_matches": 0, "pane_pid": 0}
    originals = {
        name: getattr(hub.tmuxio, name)
        for name in ("slot_pane_id", "pane_pid_matches", "pane_pid")
    }

    def counting(name):
        def inner(*args, **kwargs):
            calls[name] += 1
            return originals[name](*args, **kwargs)

        return inner

    for name in calls:
        setattr(hub.tmuxio, name, counting(name))
    try:
        reg = {"agents": {BOB: registry.get(root, BOB)}}
        snap = {
            "": {
                "panes": {"%7": {"pane_pid": "1", "slot": "pi:pi-r", "pane_created": "1"}},
                "slots": {"pi:pi-r": "%7"},
            }
        }
        online = hub.sweep_liveness(reg, root, SilentLog(), {}, {}, 100.0, snap)
        hub.refresh_display_names(reg, root, SilentLog(), snap)
    finally:
        for name, original in originals.items():
            setattr(hub.tmuxio, name, original)
    if online.get(BOB) is not True:
        problems.append(f"快照单飞: 判活失败 {online}")
    per_agent = sum(calls.values())
    if per_agent:
        problems.append(
            f"快照单飞: 快照在场时逐端单查 {per_agent} 次 {calls}——"
            "每主机必须一次 list-panes 快照喂全部 slot/pane 查询, 否则 N 端×ssh 串行成主循环地板"
        )
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
