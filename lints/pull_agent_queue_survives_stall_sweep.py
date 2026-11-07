#!/usr/bin/env python3
import importlib.util
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class SilentLog:
    def __init__(self):
        self.lines = []

    def write(self, line):
        self.lines.append(line)


def load_mcp():
    spec = importlib.util.spec_from_file_location("mailbox_mcp", ROOT / "mcp" / "mailbox_mcp.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def lint() -> list[str]:
    problems = []
    workspace = tempfile.mkdtemp(prefix="a2a-lint-")
    os.environ["A2A_MAILBOX_ROOT"] = workspace
    root = Path(workspace)
    from common import msgfmt, paths, registry, storage
    from hub import hub

    paths.ensure_layout(root)
    envelope = {
        "msg_id": "pu0000000001",
        "ack_id": "ack-pu0000000001",
        "from": "sender-h",
        "to": "zcode-worker",
        "body": "拉取型语义: 队列保持不回弹",
        "created_at": time.time() - 20000.0,
        "wake_text": msgfmt.compose_wake("sender-h", "pu0000000001", "拉取型语义: 队列保持不回弹"),
    }
    storage.enqueue(root, envelope)
    registry.upsert(root, "zcode-worker", {"agent_id": "zcode-worker", "cli": "zcode", "pane_id": "", "spawn_cmd": None, "cwd": "/tmp"})
    registry.upsert(root, "sender-h", {"agent_id": "sender-h", "cli": "claude", "pane_id": "%1", "pane_pid": "100", "cwd": "/tmp"})
    log = SilentLog()
    reg = registry.load(root)
    hub.sweep_offline_stalled(root, log, reg, {"zcode-worker": False, "sender-h": True}, time.time(), {})
    if storage.read_msg(root, "zcode-worker", "pu0000000001") is None:
        problems.append("拉取型豁免: zcode 收件方滞留超时被 mark_failed——主控语义为保留队列待 mail_poll 拉取")
    if storage.list_queue(root, "sender-h"):
        problems.append("拉取型豁免: zcode 收件方触发了 bounce 回弹信——W2 回弹规则对拉取型必须豁免")
    notified = [line for line in log.lines if "delivery-stalled" in line]
    if not notified or "不回弹" not in notified[0]:
        problems.append("拉取型豁免: 滞留超时未发 delivery-stalled 通知(30min 未取件提醒)")
    hub.sweep_offline_stalled(root, log, reg, {"zcode-worker": False, "sender-h": True}, time.time() + 60.0, {})
    if len([line for line in log.lines if "delivery-stalled" in line]) != 1:
        problems.append("拉取型豁免: stall 通知未按 stall_notified_at 幂等——每轮 sweep 将刷屏")

    legacy = dict(envelope, msg_id="pu0000000002", ack_id="ack-pu0000000002", to="codex-worker", created_at=time.time() - 20000.0)
    legacy["wake_text"] = msgfmt.compose_wake("sender-h", "pu0000000002", legacy["body"])
    storage.enqueue(root, legacy)
    registry.upsert(root, "codex-worker", {"agent_id": "codex-worker", "cli": "codex", "pane_id": "", "spawn_cmd": None, "cwd": "/tmp"})
    reg = registry.load(root)
    hub.sweep_offline_stalled(root, log, reg, {"zcode-worker": False, "codex-worker": False, "sender-h": True}, time.time(), {})
    if storage.read_msg(root, "codex-worker", "pu0000000002") is not None:
        problems.append("拉取型豁免越界: 非 zcode 的 pane-less 滞留必须维持 G1 回弹语义(mark_failed+bounce)")

    os.environ["A2A_CLI"] = "zcode"
    os.environ.pop("TMUX_PANE", None)
    detected = None
    try:
        from common import detect

        detected = detect.detect_cli()
        agent_id = detect.build_agent_id(detected, "/tmp")
        if not agent_id.startswith("zcode-"):
            problems.append(f"A2A_CLI 过桥: 检测为 {detected!r} 但身份 {agent_id!r} 未落 zcode-* 前缀")
    finally:
        os.environ.pop("A2A_CLI", None)
    if detected != "zcode":
        problems.append(f"A2A_CLI 过桥: wsl 桥透传 A2A_CLI=zcode 时 detect_cli 返回 {detected!r}")

    mcp = load_mcp()
    mcp.paths.mailbox_root = lambda: root
    mcp.do_ack("zcode-worker", "ack-pu0000000001")
    if storage.read_msg(root, "zcode-worker", "pu0000000001") is not None:
        problems.append("拉取型读侧: mail_ack 后消息未归档——无 hub Delivery 跟踪, 队列将无限重复 poll")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
