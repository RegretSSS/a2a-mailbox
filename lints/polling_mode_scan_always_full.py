#!/usr/bin/env python3
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class FakeClock:
    def __init__(self):
        self.now = 1000000.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds

    def strftime(self, fmt):
        return "lint"


def lint() -> list[str]:
    workspace = tempfile.mkdtemp(prefix="a2a-lint-")
    os.environ["A2A_MAILBOX_ROOT"] = workspace
    os.environ.pop("A2A_HUB_IDLE_REAP", None)
    from hub import hub

    clock = FakeClock()
    scopes: list[object] = []

    def fake_step(root, reg, deliveries, log, now, online, remote_cache=None, frame_cache=None, dirty_agents=None):
        scopes.append(dirty_agents)
        if len(scopes) >= 12:
            raise SystemExit(0)

    def refuse_notifier(root):
        raise OSError("polling lint")

    real_time, real_step = hub.time, hub.step
    real_notifier = hub.queuenotify.QueueNotifier
    hub.time, hub.step = clock, fake_step
    hub.queuenotify.QueueNotifier = refuse_notifier
    try:
        hub.main()
    except SystemExit:
        pass
    finally:
        hub.time, hub.step = real_time, real_step
        hub.queuenotify.QueueNotifier = real_notifier
    full_scans = sum(1 for scope in scopes if scope is None)
    if full_scans < 2:
        return [
            f"12 轮轮询循环只有 {full_scans} 次全量扫描(dirty_agents=None)——"
            "slow_due 在 sleep 前取样后陈旧用于 scan_scope, slow 块的 fresh 补判只跑 sweep 不跑 step, "
            "notifier=None 节点队内信封永远无人扫 (2026-11-12 win python 活体: rpc-inbox 信滞留 126s 零投递, "
            "同参数独立 step(dirty_agents=None) 一击即达 via=dsh-rpc)"
        ]
    return []


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
