#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def body_of(source: str, name: str) -> str:
    matched = re.search(rf"def {name}\(.*?\n(.*?)(?=\n    def |\ndef |\nclass |\Z)", source, re.S)
    return matched.group(1) if matched else ""


def lint() -> list[str]:
    problems = []
    hub_source = (ROOT / "hub" / "hub.py").read_text()
    main_body = body_of(hub_source, "main")
    if "write_online" not in main_body:
        problems.append("hub/hub.py: main 慢路径必须落 online map——mail_who 投影的 active/stale 唯一数据源")
    mcp_source = (ROOT / "mcp" / "mailbox_mcp.py").read_text()
    who_body = body_of(mcp_source, "do_who")
    if "federation.pull_all" not in who_body:
        problems.append("mcp/mailbox_mcp.py: do_who 前置 pull_all 是联邦停投的真正修复机制, 不得撤")
    if "pane_pid_matches" in who_body:
        problems.append("mcp/mailbox_mcp.py: do_who 逐 agent pane_pid_matches 每远端一条同步 ssh RTT——验活职责归 hub")
    if "load_online" not in who_body or '"state"' not in who_body:
        problems.append("mcp/mailbox_mcp.py: do_who 必须以 hub online map 投影 state(active/stale/unknown)")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
