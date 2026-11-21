#!/usr/bin/env python3
import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load_detect():
    spec = importlib.util.spec_from_file_location("detect", ROOT / "common" / "detect.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def lint() -> list[str]:
    problems = []
    detect = load_detect()
    real_uname = os.uname
    real_name = os.name
    del os.uname
    os.name = "nt"
    os.environ["COMPUTERNAME"] = "WINLAB"
    try:
        host = detect.local_host()
        if host != "WINLAB":
            problems.append(
                f"nt 环境下 local_host() 应走 COMPUTERNAME/socket 回退, 实得 {host!r}——"
                "实测 2026-11-12 win python 载入 mailbox_mcp 注册即 AttributeError "
                "(module 'os' has no attribute 'uname'), 纯 win 节点注册路径不得依赖 POSIX-only API"
            )
    except AttributeError as exc:
        problems.append(f"nt 环境下 local_host() 仍撞 POSIX-only API: {exc}")
    finally:
        os.uname = real_uname
        os.name = real_name
        os.environ.pop("COMPUTERNAME", None)
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
