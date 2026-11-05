#!/usr/bin/env python3
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

LOCAL_AGENT = "claude-host-a-a2a-mailbox"


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
    from common import federation, registry, storage
    from hub import hub

    registry.upsert(root, LOCAL_AGENT, {"agent_id": LOCAL_AGENT, "cli": "claude", "host": "localhost",
                                        "slot": "pi:claude", "pane_id": "%46", "pane_pid": "446"})
    (root / "peers.json").write_text('{"peers": ["host-b"]}')
    repatriated = {
        "msg_id": "rp0000000001", "ack_id": "ack-rp0000000001", "from": "claude-host-b-a2a-mailbox",
        "to": LOCAL_AGENT, "body": "host-b 腿在线", "in_reply_to": None, "hop": 1, "created_at": 1.0,
        "wake_text": "wake rp0000000001", "last_injected_at": 100.0,
    }
    federation.sshio.read_remote_json_status = lambda alias, rel: ("ok", {"agents": {}})
    federation.sshio.read_remote_queue_msgs = lambda alias: ("ok", [repatriated])

    result = federation.pull_peer(root, "host-b")
    if result.get("pulled") != 1:
        return [f"拉回: 已注入的远程来件未被拉回(pulled={result.get('pulled')})——收件方 mail_read 只能靠唤醒词捎带, 读不到元数据"]
    if storage.read_msg(root, LOCAL_AGENT, "rp0000000001") is None:
        return ["拉回: 本地 queue 未见拉回副本"]

    injects = {"n": 0}
    real_prime = hub.tmuxio.prime_injection
    hub.tmuxio.prime_injection = lambda *a, **k: injects.__setitem__("n", injects["n"] + 1)
    hub.tmuxio.pane_created = lambda pane, ssh_host=None: 0.0
    try:
        reg = registry.load(root)
        deliveries: dict = {}
        hub.step(root, reg, deliveries, SilentLog(), 500.0, {LOCAL_AGENT: True})
        delivery = deliveries.get(f"{LOCAL_AGENT}/rp0000000001")
        if delivery is None:
            return ["拉回: step 未接管拉回副本"]
        if delivery.state != hub.STATE_WAIT_CONFIRM:
            problems.append(
                f"拉回: 拉回副本未走 resume 态({delivery.state})——对端已注入过, 本地重注=收件方二次消费"
            )
        if injects["n"] != 0:
            problems.append(f"拉回: 对已注入消息重注 {injects['n']} 次")
    finally:
        hub.tmuxio.prime_injection = real_prime
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
