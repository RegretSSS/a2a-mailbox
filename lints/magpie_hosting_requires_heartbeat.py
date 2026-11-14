#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BRIDGE = ROOT / "common" / "magpie_bridge.py"
MCP = ROOT / "mcp" / "mailbox_mcp.py"


def lint() -> list[str]:
    problems = []
    source = BRIDGE.read_text(encoding="utf-8")
    if "magpie-bridge.json" not in source:
        problems.append("common/magpie_bridge.py: 托管判定必须以 magpie-bridge.json 心跳为唯一依据——『装了 magpie』或『配置指向网关』不构成会话被托管的证据(本机 CC 直连 z.ai 而 pi/codex 走网关的实证), 无新鲜心跳一律判未托管")
    if "HOSTING_TTL_SECONDS" not in source or "moment - ts / 1000 > HOSTING_TTL_SECONDS" not in source:
        problems.append("common/magpie_bridge.py: 心跳必须带 TTL 新鲜度闸——陈旧心跳判托管会把已切走直连的会话误标, 通知预期落空即孤儿")
    mcp_source = MCP.read_text(encoding="utf-8")
    if "magpie_bridge.magpie_hosting" not in mcp_source:
        problems.append("mcp/mailbox_mcp.py: who 的 magpie 标记必须经 magpie_bridge.magpie_hosting 投影——工具面不得自读心跳文件旁路 TTL 闸")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
