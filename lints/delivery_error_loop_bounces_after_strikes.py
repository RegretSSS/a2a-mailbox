#!/usr/bin/env python3
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
RECIPIENT = "claude-host-a-a2a-mailbox"
SENDER = "pi-host-a-a2a-mailbox"


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

    registry.upsert(root, RECIPIENT, {"cli": "claude", "pane_id": "%5", "pane_pid": "1", "slot": "claude"})
    storage.enqueue(
        root,
        {
            "msg_id": "el0000000001",
            "ack_id": "ack-el0000000001",
            "from": SENDER,
            "to": RECIPIENT,
            "body": "重放原始失败输入: 投递循环异常场景",
        },
    )

    def exploding_prime(pane_id, text, ssh_host=None):
        raise RuntimeError("deterministic boom")

    original_prime = hub.tmuxio.prime_injection
    original_quiet = hub.tmuxio.quiet_mark
    hub.tmuxio.prime_injection = exploding_prime
    hub.tmuxio.quiet_mark = lambda pane, ssh_host=None: "0"
    try:
        deliveries = {}
        log = SilentLog()
        reg = {"agents": {RECIPIENT: registry.get(root, RECIPIENT)}}
        hub.step(root, reg, deliveries, log, time.time() + 5.0, {RECIPIENT: True})
        if not deliveries:
            problems.append("预热轮应建出投递对象")
        settle_lag = hub.SETTLE_SECONDS + 1.0
        for round_index in range(hub.DELIVERY_ERROR_STRIKES):
            now = time.time() + 600.0 + settle_lag + round_index * (hub.DELIVERY_ERROR_RETRY_SECONDS + 1.0)
            hub.step(root, reg, deliveries, log, now, {RECIPIENT: True})
            if round_index < hub.DELIVERY_ERROR_STRIKES - 1:
                last = deliveries.get(f"{RECIPIENT}/el0000000001")
                if last is None:
                    problems.append(f"第 {round_index + 1} 击不应立即放弃, 应滞留节流重试")
                elif last.error_strikes != round_index + 1:
                    problems.append(f"连击计数应为 {round_index + 1}: got {last.error_strikes}")
        error_lines = [line for line in log.lines if "delivery-error" in line]
        if len(error_lines) > hub.DELIVERY_ERROR_STRIKES:
            problems.append(f"每轮一条 delivery-error 应有界: got {len(error_lines)}")
        if deliveries:
            problems.append(f"{hub.DELIVERY_ERROR_STRIKES} 击后投递对象应移除: {list(deliveries)}")
        failed = storage.msg_path(root, RECIPIENT, "el0000000001").with_suffix(".failed")
        if not failed.is_file():
            problems.append("连击耗尽应 mark_failed 落死信")
        bounce_ids = [p.name for p in (root / "queue" / SENDER).glob("*.msg")]
        if not bounce_ids:
            problems.append("连击耗尽应给发件方 enqueue_bounce 回弹信")
        if not any("连续" in line and "FAILED" in line for line in log.lines):
            problems.append("连击耗尽应写 FAILED 终态日志")
    finally:
        hub.tmuxio.prime_injection = original_prime
        hub.tmuxio.quiet_mark = original_quiet
    return problems


if __name__ == "__main__":
    failures = lint()
    for line in failures:
        print(f"FAIL: {line}")
    sys.exit(1 if failures else 0)
