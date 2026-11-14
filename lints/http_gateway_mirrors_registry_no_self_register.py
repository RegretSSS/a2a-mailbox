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
    if "module.MOUNTED_AGENT_ID = agent_id" not in source or "mounted_identity_only" not in source or "module.MOUNTED_CWD" not in source or "module.MOUNTED_CLI" not in source:
        problems.append(
            "mcp/http_gateway.py: 挂载预填必须=身份哨兵 SELF+MOUNTED_AGENT_ID+MOUNTED_CWD+MOUNTED_CLI——"
            "整条 registry 快照预填会陈旧且 ensure_self 早退永不刷新(2026-11-14 E2E 现场: pi 换窗后挂载快照 pane 投错窗); "
            "cli/cwd 须从挂载期快照携带, 网关进程 detect_cli 只会得出 unknown(2026-11-14 现场: cli=unknown 冲掉档身份, pi 扩展认领失效)"
        )
    mcp_src = (ROOT / "mcp" / "mailbox_mcp.py").read_text()
    reg_body = mcp_src.split("def register_record", 1)[-1].split("def ", 1)[0]
    if 'detect.current_pane_id() if not mounted_id else ""' not in reg_body:
        problems.append(
            "mcp/mailbox_mcp.py: mounted 注册必须 pane 恒空——gateway 进程所有档共享同一 pane 环境, "
            "网关进程检测的 pane 会把活档锚冲成错窗(历史事故: SELF 全体漂移)"
        )
    if 'explicit_id = os.environ.get(detect.AGENT_ID_ENV, "").strip() or mounted_id' not in reg_body:
        problems.append(
            "mcp/mailbox_mcp.py: mounted 注册必须 explicit_id=mounted_id 跳过 adopt 认领——"
            "否则 slot/cwd 认领分支会把第二个档吸进第一个档的 record"
        )
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
