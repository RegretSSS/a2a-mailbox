#!/usr/bin/env python3
import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

WIN_SESSION_CWD = "D:\\win-lab\\dsh-test"
POSIX_RECORD_CWD = "/mnt/d/win-lab/dsh-test"
ORIGINAL_ITEMS = [
    {"sessionId": "blank-1", "blank": True, "cwd": WIN_SESSION_CWD, "updatedAt": 50},
    {"sessionId": "hit-1", "blank": False, "cwd": WIN_SESSION_CWD, "updatedAt": 9},
    {"sessionId": "elsewhere", "blank": False, "cwd": "D:\\elsewhere", "updatedAt": 99},
]


def load_inbox():
    return importlib.import_module("common.dsh_inbox")


def lint() -> list[str]:
    problems = []
    inbox = load_inbox()
    picked = inbox.pick_session(ORIGINAL_ITEMS, POSIX_RECORD_CWD)
    if picked is None or picked.get("sessionId") != "hit-1":
        problems.append(
            f"win 会话 cwd({WIN_SESSION_CWD!r}) 对 POSIX 记录 cwd({POSIX_RECORD_CWD!r}) 未命中——"
            "实测 2026-11-12 13:40:52 hub.log queue-retry『无 cwd 匹配的非空白会话』回弹"
            "(wsl.exe 桥记录 cwd=/mnt/..., dsh host 上报 win 路径), pick_session 必须跨端规范化比对"
        )
    if inbox.pick_session(ORIGINAL_ITEMS, "/mnt/d/elsewhere") is None:
        problems.append("跨端规范化过度: 不匹配目录的会话不应被误 pick")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
