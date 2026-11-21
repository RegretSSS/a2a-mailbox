#!/usr/bin/env python3
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class SilentLog:
    def __init__(self):
        self.lines = []

    def write(self, line):
        self.lines.append(line)


class DoneProc:
    def __init__(self, output):
        self.output = output
        self.outpath = ""

    def poll(self):
        return 0


def lint() -> list[str]:
    problems = []
    workspace = tempfile.mkdtemp(prefix="a2a-lint-")
    os.environ["A2A_MAILBOX_ROOT"] = workspace
    root = Path(workspace)
    from common import msgfmt, nativebox, paths, storage
    from hub import hub

    paths.ensure_layout(root)
    envelope = {
        "msg_id": "cq0000000001",
        "ack_id": "ack-cq0000000001",
        "from": "sender-h",
        "to": "codex-master",
        "body": "queue-daemon lint: 原生队列投递不得触发 tmux 注入",
        "created_at": 1.0,
        "wake_text": msgfmt.compose_wake("sender-h", "cq0000000001", "queue-daemon lint: 原生队列投递不得触发 tmux 注入"),
    }
    storage.enqueue(root, envelope)
    record = {
        "agent_id": "codex-master",
        "cli": "codex",
        "host": "localhost",
        "pane_id": "%17",
        "pane_pid": "700",
        "cwd": "/tmp",
        "spawn_cmd": None,
        "codex_bin": "/usr/local/bin/codex",
        "codex_home": "/tmp/fake-home",
        "codex_thread": "aaaa5c8b-07a4-7f61-a73c-312c7a2d915e",
    }
    injects = {"n": 0}
    real_prime = hub.tmuxio.prime_injection
    real_created = hub.tmuxio.pane_created
    real_alive = hub.codexq.daemon_alive
    real_enqueue = hub.codexq.enqueue_async
    hub.tmuxio.prime_injection = lambda *a, **k: injects.__setitem__("n", injects["n"] + 1)
    hub.tmuxio.pane_created = lambda pane, ssh=None: 0.0
    hub.codexq.daemon_alive = lambda home: True
    proc = DoneProc("Queued message 01a1a602-754b-7c01-b965-9865d627bbd0 for thread 01a1b602-754b-7c01-b965-9865d627bbd0\n")
    proc.outpath = str(Path(workspace) / "q.out")
    Path(proc.outpath).write_text(proc.output)
    hub.codexq.enqueue_async = lambda *a, **k: (proc, proc.outpath)
    log = SilentLog()
    try:
        start = time.time()
        delivery = hub.build_delivery(envelope, record, start, root)
        if delivery is None or not delivery.queue_daemon:
            problems.append("queue-daemon: 锚定齐备且 daemon 活着时必须建原生投递, 否则退回 tmux 注入链路")
            return problems
        delivery.dispatch_queue_daemon(root, log, start, record)
        if delivery.state != hub.STATE_WAIT_NATIVE or delivery.queue_proc is None:
            problems.append("queue-daemon: dispatch 后必须 WAIT_NATIVE 持子进程等回执")
        if float(storage.read_msg(root, "codex-master", "cq0000000001").get("last_injected_at") or 0) != start:
            problems.append("queue-daemon: dispatch 未 stamp last_injected_at, hub 重启将重投")

        delivery.tick(root, log, start + 1.0, True, None)
        if delivery.state != hub.STATE_WAIT_CONFIRM:
            problems.append("queue-daemon: Queued message 回执到达必须转 WAIT_CONFIRM")
        if not nativebox.rcpt_exists(root, "codex-master", "cq0000000001"):
            problems.append("queue-daemon: 回执未落 rcpt 文件——hub 重启后无法恢复到 WAIT_CONFIRM")
        storage.write_ack(root, "ack-cq0000000001", "codex-master")
        delivery.tick(root, log, start + 2.0, True, None)
        if delivery.state != hub.STATE_DONE:
            problems.append("queue-daemon: ack 到达必须 DONE")
        if injects["n"] != 0:
            problems.append("queue-daemon: dispatch→回执→ack 全链不允许 tmux 注入")

        hub.codexq.daemon_alive = lambda home: False
        record2 = dict(record)
        envelope2 = dict(envelope, msg_id="cq0000000002", ack_id="ack-cq0000000002")
        envelope2["wake_text"] = msgfmt.compose_wake("sender-h", "cq0000000002", envelope["body"])
        delivery2 = hub.build_delivery(envelope2, record2, start, root)
        if delivery2 is not None and delivery2.native:
            problems.append("queue-daemon: daemon 死亡时必须放弃原生通道(降级 tmux), 不得盲投")

        record3 = dict(record, codex_thread="")
        delivery3 = hub.build_delivery(envelope, record3, start, root)
        if delivery3 is not None and delivery3.native:
            problems.append("queue-daemon: thread 锚缺失时必须放弃原生通道, 不得盲投")
    finally:
        hub.tmuxio.prime_injection = real_prime
        hub.tmuxio.pane_created = real_created
        hub.codexq.daemon_alive = real_alive
        hub.codexq.enqueue_async = real_enqueue
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
