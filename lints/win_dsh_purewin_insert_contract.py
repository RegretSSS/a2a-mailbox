#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "deploy" / "dsh" / "cordis.patch.purewin.yml"
IDENTITY_ENV_KEYS = (
    "A2A_AGENT_ID",
    "A2A_CLI",
    "A2A_PANELESS",
    "A2A_RPC_INBOX_URL",
    "A2A_HOST_TAG",
)


def lint() -> list[str]:
    problems = []
    text = TEMPLATE.read_text()
    if "wsl.exe" in text:
        problems.append(f"{TEMPLATE.name}: 纯 win 主形态运行时零 wsl.exe——command 不得再指 wsl.exe 桥")
    if "WSLENV" in text:
        problems.append(f"{TEMPLATE.name}: 纯 win 形态无跨界 env, 不应出现 WSLENV 透传(那是桥形态变体的配件)")
    if "A2A_MAILBOX_ROOT" not in text:
        problems.append(f"{TEMPLATE.name}: 缺 A2A_MAILBOX_ROOT——纯 win 形态写路径全部落 win 原生 NTFS 根")
    if "A2A_HUB_IDLE_REAP: '1'" not in text:
        problems.append(f"{TEMPLATE.name}: 缺 A2A_HUB_IDLE_REAP '1'——纯 win 节点 hub 挂靠 MCP 首调拉起, 须空闲自回收")
    if "PYTHONUTF8: '1'" not in text:
        problems.append(
            f"{TEMPLATE.name}: 缺 PYTHONUTF8 '1'——registry.json/信封含非 ASCII cwd, "
            "非 UTF-8 locale 机器的 win python 默认按 ANSI 码页读写会炸注册表"
        )
    missing = [key for key in IDENTITY_ENV_KEYS if key not in text]
    if missing:
        problems.append(f"{TEMPLATE.name}: 五键身份 env 缺 {missing} (显式身份短路 cwd/claims 认领)")
    if "<repo-unc>" not in text or "mailbox_mcp.py" not in text:
        problems.append(f"{TEMPLATE.name}: args 应以 <repo-unc> 占位符 + mailbox_mcp.py 指向仓内脚本 (代码只读加载走 UNC, 2026-11-12 活体定谳)")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
