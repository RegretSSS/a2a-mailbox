#!/usr/bin/env python3
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALICE = "claude-host-a-a2a-mailbox"
BOB = "pi-host-a-a2a-mailbox"


def prepare():
    workspace = tempfile.mkdtemp(prefix="a2a-lint-")
    os.environ["A2A_MAILBOX_ROOT"] = workspace
    sys.path.insert(0, str(ROOT))
    from common import registry

    spec = importlib.util.spec_from_file_location("mailbox_mcp", ROOT / "mcp" / "mailbox_mcp.py")
    mailbox_mcp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mailbox_mcp)
    root = Path(workspace)
    for agent_id in (ALICE, BOB):
        registry.upsert(root, agent_id, {"cli": "pi", "pane_id": "%1", "pane_pid": "1"})
    (root / "peers.json").write_text('{"peers": ["deadpeer"]}')
    return mailbox_mcp, root


def lint() -> list[str]:
    problems = []
    mailbox_mcp, root = prepare()
    calls = {"count": 0}

    def unreachable(alias, rel):
        calls["count"] += 1
        return ("unreachable", None)

    mailbox_mcp.sshio.read_remote_json_status = unreachable
    mailbox_mcp.PEER_UNREACHABLE_CACHE.clear()
    first = json.loads(mailbox_mcp.do_send(BOB, ALICE, "任务: 读 DESIGN.md 并回函", in_reply_to="dead00000001"))
    if not (first.get("ok") is False and "不可达" in str(first.get("error")) and "不存在" not in str(first.get("error"))):
        problems.append(f"peer 不可达: 报错必须区分『不可达』与『不存在』——掉线被报成不存在会教 agent 断 in_reply_to 链: {first}")
    second = json.loads(mailbox_mcp.do_send(BOB, ALICE, "任务: 读 DESIGN.md 并回函", in_reply_to="dead00000002"))
    if "不可达" not in str(second.get("error")):
        problems.append(f"peer 不可达: 缓存期内二次回函仍应报不可达: {second}")
    if calls["count"] > 1:
        problems.append(f"peer 不可达: 缓存未短路——不可达 peer 每条 in_reply_to 都 ssh 探测 {calls['count']} 次")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
