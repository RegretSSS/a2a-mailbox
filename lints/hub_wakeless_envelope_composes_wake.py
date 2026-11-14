#!/usr/bin/env python3
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

LEGACY_ENVELOPE = {
    "msg_id": "1408c759cdde",
    "ack_id": "ack-1408c759cdde",
    "from": "pi-host-b-aicontest-clinical-note",
    "to": "claude-host-b-----",
    "to_instance": "",
    "body": "桥 v3inc 落版本+四点回执",
    "ts": "2026-11-12T10:17:23+0800",
}


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
    from hub import hub

    delivery = hub.Delivery(dict(LEGACY_ENVELOPE), 1000.0, pane_id="%5")
    composed = hub.msgfmt.compose_wake(LEGACY_ENVELOPE["from"], LEGACY_ENVELOPE["msg_id"], LEGACY_ENVELOPE["body"])
    resolved = delivery.wake_text_resolved()
    if resolved != composed:
        problems.append(f"wakeless envelope 应回退 compose_wake: got {resolved[:40]!r}")
    if delivery.wake_text_resolved() is not resolved:
        problems.append("wake_text_resolved 应缓存复用, 不应每轮重算")

    primed = {}
    original_prime = hub.tmuxio.prime_injection
    original_quiet = hub.tmuxio.quiet_mark
    original_stamp = hub.storage.stamp_injected

    def fake_prime(pane_id, text, ssh_host=None):
        primed["pane_id"] = pane_id
        primed["text"] = text

    hub.tmuxio.prime_injection = fake_prime
    hub.tmuxio.quiet_mark = lambda pane, ssh_host=None: "0"
    hub.storage.stamp_injected = lambda *a, **k: None
    try:
        delivery.inject_round(root, SilentLog(), 1600.0)
    except Exception as exc:
        problems.append(f"inject_round 对 wakeless 信封抛异常(原 KeyError 风暴根因): {exc!r}")
    finally:
        hub.tmuxio.prime_injection = original_prime
        hub.tmuxio.quiet_mark = original_quiet
        hub.storage.stamp_injected = original_stamp
    if primed.get("text") != composed:
        problems.append(f"注入文本应等于回退 compose: got {str(primed.get('text'))[:40]!r}")

    with_wake = dict(LEGACY_ENVELOPE, wake_text="[A2A] from=x id=y\n显式唤醒词")
    delivery2 = hub.Delivery(with_wake, 1000.0, pane_id="%5")
    if delivery2.wake_text_resolved() != "[A2A] from=x id=y\n显式唤醒词":
        problems.append("带 wake_text 的信封应原样使用存储值, 不得改写")
    return problems


if __name__ == "__main__":
    failures = lint()
    for line in failures:
        print(f"FAIL: {line}")
    sys.exit(1 if failures else 0)
