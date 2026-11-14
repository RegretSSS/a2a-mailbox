#!/usr/bin/env python3
import importlib.util
import os
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load_mcp(recorded_threads):
    spec = importlib.util.spec_from_file_location("mailbox_mcp_startup_hb", ROOT / "mcp" / "mailbox_mcp.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class RecordingThread:
        def __init__(self, target=None, **kwargs):
            recorded_threads.append(target)

        def start(self):
            return None

    module.threading = types.SimpleNamespace(Thread=RecordingThread)
    module.mcp.run = lambda: None
    return module


def lint() -> list[str]:
    problems = []
    recorded_threads = []
    module = load_mcp(recorded_threads)
    workspace = tempfile.mkdtemp(prefix="a2a-lint-hb-")
    os.environ["A2A_MAILBOX_ROOT"] = workspace
    os.environ["A2A_AGENT_ID"] = "dsh-host-a-win"
    os.environ["A2A_CLI"] = "dsh"
    os.environ["A2A_PANELESS"] = "1"
    os.environ["A2A_RPC_INBOX_URL"] = "http://127.0.0.1:3081"
    os.environ["A2A_HOST_TAG"] = "host-a"
    os.environ.pop("TMUX_PANE", None)
    os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
    module.paths.mailbox_root = lambda: Path(workspace)
    module.boot_hub_if_absent = lambda root: None
    module.main()
    armed = any(target is module.refresh_registration_forever for target in recorded_threads)
    if not armed:
        problems.append(
            "main() 启动注册成功后未武装 300s 心跳线程——paneless rpc 档档位活性=MCP 进程存活, "
            "实测 2026-11-12 常驻 win host 的 MCP 子进程(main 走 self_register 直调)注册一次后 "
            "零刷新, 记录 600s stale 后 hub 扫描 gate 拒收信、1800s 被 prune; "
            "启动路径必须经 ensure_self() (注册成功即 start_heartbeat_thread)"
        )
    if module.SELF.get("agent_id") != "dsh-host-a-win":
        problems.append(f"main() 启动注册未落显式身份: SELF={module.SELF.get('agent_id')!r}")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
