#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT_MD = ROOT / "pi" / "agents" / "general-purpose.md"

MAILBOX_TOOLS = (
    "mcp__mailbox__mail_send",
    "mcp__mailbox__mail_poll",
    "mcp__mailbox__mail_read",
    "mcp__mailbox__mail_ack",
    "mcp__mailbox__mail_who",
    "mcp__mailbox__mail_group",
)


def lint() -> list[str]:
    problems = []
    if not AGENT_MD.exists():
        return [
            "pi/agents/general-purpose.md 缺失——pi-subagents 内置 general-purpose 的 builtinToolNames 为 undefined"
            "(未窄化=全量工具含 MCP), subagent 能以主档身份调 mailbox 六工具(冒名发信/ack 消费/收向越权); "
            "必须同名覆盖并在 disallowed_tools 全量封禁 mcp__mailbox__*"
        ]
    source = AGENT_MD.read_text()
    if "name: general-purpose" not in source:
        problems.append("pi/agents/general-purpose.md: 覆盖文件必须 name: general-purpose 同名命中内置")
    for tool in MAILBOX_TOOLS:
        if tool not in source:
            problems.append(f"pi/agents/general-purpose.md: disallowed_tools 缺 {tool}——六工具面必须全封")
    if "mcp__" in source.replace("mcp__mailbox__", ""):
        problems.append("pi/agents/general-purpose.md: 出现 mailbox 之外的 mcp__ 条目——黑名单只封 mailbox, 误伤其他 MCP server 属过封")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
