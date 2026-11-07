#!/usr/bin/env python3
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
BOB = "pi-host-a-a2a-mailbox"
OTHER = "codex-host-a-workspace"


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

    for agent_id in (BOB, OTHER):
        registry.upsert(root, agent_id, {"cli": "pi", "pane_id": "%7", "pane_pid": "1", "slot": "pi:x"})
        envelope = {
            "msg_id": f"ed{agent_id[-4:]}",
            "ack_id": f"ack-ed{agent_id[-4:]}",
            "from": "claude-host-a-a2a-mailbox",
            "to": agent_id,
            "body": "任务: 读 DESIGN.md 并回函",
            "last_injected_at": 0.0,
        }
        storage.enqueue(root, envelope)
    scanned = []
    original_list = storage.list_queue
    original_capture = hub.tmuxio.capture_joined_bottom
    original_inject = hub.tmuxio.inject_wake

    def counting_list(r, agent_id):
        scanned.append(agent_id)
        return original_list(r, agent_id)

    def blank_capture(pane, line_count=60, ssh_host=None):
        return ""

    def no_inject(pane, text, ssh_host=None):
        pass

    hub.storage.list_queue = counting_list
    hub.tmuxio.capture_joined_bottom = blank_capture
    hub.tmuxio.inject_wake = no_inject
    try:
        reg = {"agents": {a: registry.get(root, a) for a in (BOB, OTHER)}}
        hub.step(root, reg, {}, SilentLog(), 100.0, {BOB: True, OTHER: True}, dirty_agents={BOB})
    finally:
        hub.storage.list_queue = original_list
        hub.tmuxio.capture_joined_bottom = original_capture
        hub.tmuxio.inject_wake = original_inject
    if scanned != [BOB]:
        problems.append(
            f"事件驱动: dirty={{BOB}} 时扫描了 {scanned}——inotify 事件轮必须只扫事件涉及的 agent,"
            " 全量重扫只许发生在慢路径/降级/registry 变更轮"
        )
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
