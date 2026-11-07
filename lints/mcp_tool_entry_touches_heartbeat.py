#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def lint() -> list[str]:
    problems = []
    source = (ROOT / "mcp" / "mailbox_mcp.py").read_text()
    for name in ("do_send", "do_poll", "do_read", "do_ack", "do_who", "do_group", "do_request_join", "do_pending_joins", "do_admit", "do_revoke", "do_group_gate"):
        body = re.search(rf"def {name}\([^\n]*\) -> str:\n(.*?)(?=\ndef |\n@mcp|\Z)", source, re.S)
        if not body:
            problems.append(f"mcp/mailbox_mcp.py: {name} 函数缺失")
            continue
        first = body.group(1).lstrip().splitlines()[0] if body.group(1).strip() else ""
        if "touch_heartbeat()" not in first:
            problems.append(
                f"mcp/mailbox_mcp.py {name}: 入口未 touch_heartbeat——hub idle-reap 会把活跃 MCP 判死回收(纯 win 节点自活)"
            )
    if "touch_heartbeat()" not in re.search(r"def self_register\(.*?\n(.*?)(?=\ndef )", source, re.S).group(1):
        problems.append("mcp/mailbox_mcp.py self_register: 未 touch_heartbeat——注册期心跳缺席会被 idle-reap 误判")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
