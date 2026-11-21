#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "deploy" / "dsh" / "cordis.patch.win.yml"
REQUIRED_ENV_KEYS = (
    "A2A_AGENT_ID/u",
    "A2A_CLI/u",
    "A2A_PANELESS/u",
    "A2A_RPC_INBOX_URL/u",
    "A2A_HOST_TAG/u",
)


def lint() -> list[str]:
    problems = []
    text = TEMPLATE.read_text()
    if "wsl.exe" not in text:
        problems.append(f"{TEMPLATE.name}: win 侧 stdio 挂载必须以 wsl.exe 为 command")
    if "\\wsl.localhost" in text:
        problems.append(
            f"{TEMPLATE.name}: 出现 \\\\wsl.localhost 路径——桥形态 (根留 WSL) 的写路径不得经 UNC, "
            "msvcrt 锁过 9P 报 EDEADLK (2026-11-12 win python 活体: registry.lock 全写路径废), "
            "须用 wsl.exe 桥 + WSL 侧 POSIX 路径; 纯 win 主形态 (win NTFS 根+UNC 只读加载) 另见 win_dsh_purewin_insert_contract"
        )
    if "A2A_MAILBOX_ROOT" in text:
        problems.append(
            f"{TEMPLATE.name}: A2A_MAILBOX_ROOT 不属于 win 挂载 env——wsl.exe 桥内 mailbox root 取 WSL 原生默认, 显式指 UNC 即入锁死区"
        )
    missing = [key for key in REQUIRED_ENV_KEYS if key not in text]
    if missing:
        problems.append(f"{TEMPLATE.name}: WSLENV 透传缺五键中的 {missing} (Windows→WSL env 不自动过境)")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
