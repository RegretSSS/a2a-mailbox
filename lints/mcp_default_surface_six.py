#!/usr/bin/env python3
import asyncio
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXPECTED = {"mail_ack", "mail_group", "mail_poll", "mail_read", "mail_send", "mail_who"}


def lint() -> list[str]:
    problems = []
    spec = importlib.util.spec_from_file_location("mailbox_surface", ROOT / "mcp" / "mailbox_mcp.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    names = {tool.name for tool in asyncio.run(module.mcp.list_tools())}
    if len(names) > 6:
        problems.append(
            f"mcp/mailbox_mcp.py: 默认工具面 {len(names)} 个超过 6——主控裁定群组类动词必须收敛进 mail_group 调度器, 不许平铺新工具"
        )
    extra = sorted(names - EXPECTED)
    missing = sorted(EXPECTED - names)
    if extra:
        problems.append(f"mcp/mailbox_mcp.py: 工具面出现核心六件套之外的平铺工具 {extra}——group 动作走 mail_group(action=...)")
    if missing:
        problems.append(f"mcp/mailbox_mcp.py: 核心工具缺失 {missing}——唤醒文本契约指向的工具必须常在")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
