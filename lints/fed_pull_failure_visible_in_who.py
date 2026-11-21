#!/usr/bin/env python3
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALICE = "claude-host-a-a2a-mailbox"
REMOTE_CAROL = "claude-host-b-ws"


def prepare():
    workspace = tempfile.mkdtemp(prefix="a2a-lint-")
    os.environ["A2A_MAILBOX_ROOT"] = workspace
    sys.path.insert(0, str(ROOT))
    from common import registry

    spec = importlib.util.spec_from_file_location("mailbox_mcp", ROOT / "mcp" / "mailbox_mcp.py")
    mailbox_mcp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mailbox_mcp)
    root = Path(workspace)
    registry.upsert(root, ALICE, {"cli": "claude", "pane_id": "%1", "pane_pid": "1"})
    registry.upsert(root, REMOTE_CAROL, {"cli": "claude", "pane_id": "%9", "pane_pid": "9", "ssh_alias": "deadpeer"})
    (root / "peers.json").write_text('{"peers": ["deadpeer"]}')
    mailbox_mcp.sshio.read_remote_json_status = lambda alias, rel: ("unreachable", None)
    return mailbox_mcp, root


def lint() -> list[str]:
    problems = []
    mailbox_mcp, _ = prepare()
    result = json.loads(mailbox_mcp.do_who(ALICE))
    peers = result.get("peers") or []
    dead = [item for item in peers if item.get("peer") == "deadpeer"]
    if not dead or dead[0].get("ok") is not False or "unreachable" not in str(dead[0].get("status")):
        problems.append(f"peer 拉取失败必须在 mail_who 输出 peers 状态——agent 需要知道联邦哪一侧掉线: {peers}")
    by_id = {item.get("agent_id"): item for item in result.get("agents", [])}
    carol = by_id.get(REMOTE_CAROL, {})
    if carol.get("peer_down") is not True:
        problems.append(f"掉线 peer 的远端记录必须带 peer_down——陈旧副本与活记录无差别会误导投递决策: {carol}")
    if by_id.get(ALICE, {}).get("peer_down"):
        problems.append("本机记录不应带 peer_down")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
