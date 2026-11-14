#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GATEWAY = ROOT / "mcp" / "http_gateway.py"


def lint() -> list[str]:
    problems = []
    source = GATEWAY.read_text()
    guard = source.split("class GatewayGuard", 1)[-1].split("async def healthz", 1)[0]
    if "registered_ids" not in guard:
        problems.append(
            "mcp/http_gateway.py: GatewayGuard 必须对 /{agent_id}/mcp 现校验档在册——"
            "Mount 启动时固化+MODULES 缓存, forget/prune 后路由原样存活, "
            "已注销身份仍可发信且收件方 mail_who 不可见无法回信(幽灵档, 双路审计共识 P1)"
        )
    if "agent not registered" not in guard or "404" not in guard:
        problems.append("mcp/http_gateway.py: 幽灵档拦截必须 404 并带 agent not registered 错误体")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
