#!/usr/bin/env python3
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOB = "pi-host-a-lintrespawn"
BOB_CWD = tempfile.mkdtemp(prefix="a2a-respawn-cwd-")


def prepare():
    workspace = tempfile.mkdtemp(prefix="a2a-lint-")
    os.environ["A2A_MAILBOX_ROOT"] = workspace
    os.environ["A2A_HOST_TAG"] = "lint"
    sys.path.insert(0, str(ROOT))
    from common import registry, storage
    spec = importlib.util.spec_from_file_location("mailbox_mcp", ROOT / "mcp" / "mailbox_mcp.py")
    mailbox_mcp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mailbox_mcp)
    root = Path(workspace)
    registry.upsert(root, BOB, {"cli": "pi", "pane_id": "%7", "pane_pid": "7", "cwd": BOB_CWD})
    storage.write_online(root, {BOB: False}, now=1.0)
    return mailbox_mcp, root


def lint() -> list[str]:
    problems = []
    mailbox_mcp, root = prepare()
    spawned = []

    def fake_popen(argv, **kwargs):
        spawned.append((list(argv), kwargs.get("cwd")))

        class Proc:
            def poll(self):
                return 0

        return Proc()

    real_popen = mailbox_mcp.subprocess.Popen
    real_which = mailbox_mcp.shutil.which
    mailbox_mcp.subprocess.Popen = fake_popen
    mailbox_mcp.shutil.which = lambda name: f"/usr/local/bin/{name}"
    try:
        note = mailbox_mcp.respawn_offline_target(root, BOB)
    finally:
        mailbox_mcp.subprocess.Popen = real_popen
        mailbox_mcp.shutil.which = real_which
    if not spawned:
        problems.append("respawn_offline_target: 确认下线的 pi 档未触发后台拉起——离线自动恢复链断裂")
        return problems
    argv, cwd = spawned[0]
    if "-c" not in argv:
        problems.append(f"respawn_offline_target: pi 拉起 argv={argv} 缺 -c——裸拉是失忆重启, 档原会话状态全丢")
    if cwd != BOB_CWD:
        problems.append(f"respawn_offline_target: pi 拉起 cwd={cwd!r} 而非档 cwd——HTTP 网关形态下 MCP 进程 cwd 与档无关, 不定向则 -c 续到错误目录的会话")
    if not note:
        problems.append("respawn_offline_target: 拉起后未返回提示语——发件方无从知晓已触发恢复")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
