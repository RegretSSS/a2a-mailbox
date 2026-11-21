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
    from common import registry, storage
    from hub import hub

    envelope = {"msg_id": "rn0000000001", "ack_id": "ack-rn0000000001", "from": "a", "to": BOB,
                "body": "x", "created_at": 1.0, "wake_text": "w"}
    storage.enqueue(root, envelope)
    registry.upsert(root, BOB, {"agent_id": BOB, "cli": "codex", "host": "localhost",
                                 "pane_id": "%2", "pane_pid": "200", "slot": "pi:oldwin", "display_name": "oldwin"})
    reg = registry.load(root)
    snapshots = {"": {"panes": {"%2": {"pane_pid": "200", "slot": "pi:newwin", "pane_created": "1"}},
                      "slots": {"pi:newwin": "%2"}}}
    online = hub.sweep_liveness(reg, root, SilentLog(), {}, {}, 100.0, snapshots)
    pruned_by_old_order = hub.prune_registry(reg, root, SilentLog(), online, 100.0)
    if not pruned_by_old_order:
        problems.append("改名误杀重放失效: sweep 先跑(旧 slot 判死)必须重现即时注销——重放帧/注册表构造有误, 此 lint 失去守护力")

    registry.upsert(root, BOB, {"agent_id": BOB, "cli": "codex", "host": "localhost",
                                 "pane_id": "%2", "pane_pid": "200", "slot": "pi:oldwin", "display_name": "oldwin"})
    reg = registry.load(root)
    hub.refresh_display_names(reg, root, SilentLog(), snapshots)
    online = hub.sweep_liveness(reg, root, SilentLog(), {}, {}, 100.0, snapshots)
    pruned = hub.prune_registry(reg, root, SilentLog(), online, 100.0)
    if pruned or BOB not in reg["agents"]:
        problems.append(f"改名误杀: refresh 先行后改名窗口仍被注销——rename 会吞掉在途邮件: {pruned}")
    if reg["agents"].get(BOB, {}).get("slot") != "pi:newwin":
        problems.append("改名误杀: refresh 未按 pane_id 锚定刷新 slot")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
