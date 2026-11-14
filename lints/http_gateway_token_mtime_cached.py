#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GATEWAY = ROOT / "mcp" / "http_gateway.py"


def lint() -> list[str]:
    problems = []
    source = GATEWAY.read_text()
    token_fn = source.split("def token_state", 1)[-1].split("def registered_ids", 1)[0]
    if "st_mtime" not in token_fn or "TOKEN_CACHE" not in token_fn:
        problems.append(
            "mcp/http_gateway.py: token_state 必须按 mtime 缓存——每请求 open/read token 文件是 "
            "热路径 IO 违例(一次工具交互 3-4 个 POST=3-4 次文件系统往返)"
        )
    if "except (OSError, ValueError)" not in token_fn:
        problems.append(
            "mcp/http_gateway.py: token 读必须捕 (OSError, ValueError)——UnicodeDecodeError 是 "
            "ValueError 子类, 运维写入非 UTF-8 字节时逃逸成 500 崩全工具面"
        )
    guard = source.split("class GatewayGuard", 1)[-1].split("async def healthz", 1)[0]
    if "token_state(" not in guard:
        problems.append("mcp/http_gateway.py: guard 必须走 token_state 缓存路径, 禁绕开直读 token 文件")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
