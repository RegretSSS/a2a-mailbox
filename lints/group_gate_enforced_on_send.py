#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def lint() -> list[str]:
    problems = []
    mcp = (ROOT / "mcp" / "mailbox_mcp.py").read_text()
    send_body = re.search(r"def do_send\(.*?\n(.*?)(?=\ndef |\Z)", mcp, re.S)
    if not send_body or "send_gate_error(" not in send_body.group(1):
        problems.append(
            "mcp/mailbox_mcp.py do_send: 未调 send_gate_error——subagent scope 锁与 group-only 闸必须在发送口即时拒绝"
        )
    gate_body = re.search(r"def send_gate_error\(.*?\n(.*?)(?=\ndef |\Z)", mcp, re.S)
    if not gate_body or "peer_of" not in gate_body.group(1) or "group_only" not in gate_body.group(1):
        problems.append("mcp/mailbox_mcp.py send_gate_error: 双锁缺一(subagent peer_of / 收件方 group_only)")
    hub = (ROOT / "hub" / "hub.py").read_text()
    step_body = re.search(r"def step\(.*?\n(.*?)(?=\ndef |\Z)", hub, re.S)
    if not step_body or "group-reject" not in step_body.group(1) or "scope-reject" not in step_body.group(1):
        problems.append(
            "hub/hub.py step: 投递前缺 group/scope 复验——绕过 MCP 直写队列的信必须同样拒收回弹"
        )
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
