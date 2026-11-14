#!/usr/bin/env python3
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

LOCAL_AGENT = "claude-host-a-a2a-mailbox"


def lint() -> list[str]:
    problems = []
    workspace = tempfile.mkdtemp(prefix="a2a-lint-")
    os.environ["A2A_MAILBOX_ROOT"] = workspace
    root = Path(workspace)
    from common import federation, registry

    registry.upsert(root, LOCAL_AGENT, {"agent_id": LOCAL_AGENT, "cli": "claude", "host": "localhost", "pane_id": "%46"})
    calls = {"n": 0}
    probe_args = []

    def fake_snapshot(alias, probe_ids):
        calls["n"] += 1
        probe_args.append((alias, list(probe_ids)))
        return ("ok", {"registry": {"agents": {}}, "queue": [], "settled": {}})

    federation.sshio.read_remote_federation_snapshot = fake_snapshot

    result = federation.pull_peer(root, "host-b")
    if result.get("ok") is not True:
        return [f"快照路径失效: pull_peer ok={result.get('ok')} status={result.get('status')}"]
    if calls["n"] != 1:
        problems.append(
            f"单往返: pull_peer 发起 {calls['n']} 次远端快照(期望 1)——"
            "2026-11-12 慢链路案: tailscale p2p 断链回落 DERP(RTT 1-1.7s), 老 pull_peer 串行 3+ 次 ssh 往返"
            "(registry 1 + inbound 1 + mirrored 重复拉队列 1 + 每条 settle 1-2), mail_who 一次调用几十秒"
        )
    if not hasattr(federation.sshio, "read_remote_federation_snapshot"):
        problems.append("单往返: sshio 缺 read_remote_federation_snapshot")
    if hasattr(federation.sshio, "read_remote_queue_msgs"):
        problems.append("单往返: read_remote_queue_msgs 死路径复活——联邦拉取禁止退回多次往返形态")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
