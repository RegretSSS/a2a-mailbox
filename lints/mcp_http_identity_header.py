#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MCP = ROOT / "mcp" / "mailbox_mcp.py"
GATEWAY = ROOT / "mcp" / "http_gateway.py"


def lint() -> list[str]:
    problems = []
    source = MCP.read_text()
    tools = source.count("self_id, blocked = caller_binding(ctx)")
    if tools != 6:
        problems.append(f"mcp/mailbox_mcp.py: 六工具入口必须全部经 caller_binding(实际 {tools})——绕过即无身份判定")
    binding = source.split("def caller_binding", 1)[-1].split("def ", 1)[0]
    if 'request.headers.get("x-a2a-agent")' not in binding:
        problems.append("mcp/mailbox_mcp.py: http 身份判据必须是 X-A2A-Agent 请求头")
    if "registry.get(paths.mailbox_root(), claimed) is not None" not in binding:
        problems.append("mcp/mailbox_mcp.py: header 身份必须在册校验——不校验则任意字符串冒名任何档")
    if 'return "", (' not in binding or "X-A2A-Agent" not in binding:
        problems.append("mcp/mailbox_mcp.py: http 无合法身份必须拒绝返回错误")
    if 'mounted = str(SELF.get("agent_id") or "")' not in binding or "与挂载身份" not in binding:
        problems.append(
            "mcp/mailbox_mcp.py: 网关挂载(SELF 预填)时挂载身份必须优先且 header 不一致拒绝——"
            "header 压过挂载身份则持 token 者在 /agent-a/mcp 上可冒充任意在册档(2026-11-13 双线审计同判)"
        )
    for name in ("mail_send", "mail_poll", "mail_read", "mail_ack", "mail_who", "mail_group"):
        head = source.split(f"def {name}(", 1)[-1].split(")", 1)[0]
        if "ctx: Context | None = None" not in head:
            problems.append(f"mcp/mailbox_mcp.py: {name} 签名缺 ctx: Context | None = None(fastmcp 依类型注入)")
    gateway = GATEWAY.read_text()
    if "hubkeep.ensure_hub_running()" not in gateway:
        problems.append("mcp/http_gateway.py: main 必须 ensure_hub_running——MCP 起来检查没 hub 就拉起(detached)")
    if "memoryguard.trim_now" not in gateway:
        problems.append("mcp/http_gateway.py: 常驻网关必须挂周期 malloc_trim——长跑漂移 17h 实测 66->104MB")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
