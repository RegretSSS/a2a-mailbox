#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GATEWAY = ROOT / "mcp" / "http_gateway.py"


def lint() -> list[str]:
    problems = []
    source = GATEWAY.read_text()
    if "ensure_self" in source:
        problems.append(
            "mcp/http_gateway.py: 禁调 ensure_self——gateway 进程所有 agent 实例共享同一 pane 环境, "
            "自注册的 slot 认领分支会把第二个档吸进第一个档的 record(SELF 全体漂移), "
            "且 upsert 会用网关进程 cwd/pane_id 冲掉 stdio 面活档锚"
        )
    if "module.SELF = dict(record)" not in source:
        problems.append("mcp/http_gateway.py: 身份必须镜像 registry 记录(module.SELF = dict(record))——registry 即真相, 不走注册路径")
    if ".lifespan(app)" not in source:
        problems.append(
            "mcp/http_gateway.py: 子 app lifespan 必须以 sub.lifespan(app) 带参调用进 AsyncExitStack——"
            "fastmcp 的 session_manager 在 lifespan 工厂内才创建, 漏传播则一切请求报 "
            "StreamableHTTPSessionManager task group not initialized"
        )
    if "registry.load(root)" not in source or "load_agent_module" not in source:
        problems.append("mcp/http_gateway.py: 必须启动时预挂载全部在册档(registry.load 遍历)——动态 mount 无法事后补 lifespan")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
