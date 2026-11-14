import importlib.util
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import codexq, lockfile, paths, queuenotify

import importlib

_hub_spec = importlib.util.spec_from_file_location(
    "hub_win_node", Path(__file__).resolve().parent.parent / "hub" / "hub.py"
)
hubd = importlib.util.module_from_spec(_hub_spec)
_hub_spec.loader.exec_module(hubd)

_mcp_spec = importlib.util.spec_from_file_location(
    "mailbox_mcp_win", Path(__file__).resolve().parent.parent / "mcp" / "mailbox_mcp.py"
)
mailbox_mcp = importlib.util.module_from_spec(_mcp_spec)
_mcp_spec.loader.exec_module(mailbox_mcp)


def test_lockfile_exclusive_is_mutual(tmp_path):
    guard = tmp_path / "guard.lock"
    guard.write_text("")
    first = guard.open("r+")
    lockfile.lock_exclusive(first)
    second = guard.open("r+")
    try:
        lockfile.lock_exclusive(second)
        raised = False
    except OSError:
        raised = True
    assert raised
    lockfile.unlock(first)
    lockfile.lock_exclusive(second)
    lockfile.unlock(second)
    first.close()
    second.close()


def test_idle_reap_gates(tmp_path, monkeypatch):
    root = tmp_path
    paths.ensure_layout(root)
    now = time.time()
    started = now - 2 * hubd.IDLE_REAP_SECONDS
    monkeypatch.delenv(hubd.IDLE_REAP_ENV, raising=False)
    assert hubd.idle_reap_due(root, {"agents": {}}, {}, now, started) is False

    monkeypatch.setenv(hubd.IDLE_REAP_ENV, "1")
    assert hubd.idle_reap_due(root, {"agents": {}}, {}, now, now) is False
    assert hubd.idle_reap_due(root, {"agents": {}}, {"a/m1": object()}, now, started) is False
    fresh_agent = {"agents": {"a": {"last_seen": now}}}
    assert hubd.idle_reap_due(root, fresh_agent, {}, now, started) is False
    (root / paths.QUEUE_DIR / "a").mkdir(parents=True)
    (root / paths.QUEUE_DIR / "a" / "m1.msg").write_text("{}")
    assert hubd.idle_reap_due(root, {"agents": {}}, {}, now, started) is False
    (root / paths.QUEUE_DIR / "a" / "m1.msg").unlink()
    assert hubd.idle_reap_due(root, {"agents": {}}, {}, now, started) is False
    (root / paths.MCP_HEARTBEAT_FILE).write_text("")
    assert hubd.idle_reap_due(root, {"agents": {}}, {}, now, started) is False
    stale = now - 2 * hubd.IDLE_REAP_SECONDS
    os.utime(root / paths.MCP_HEARTBEAT_FILE, (stale, stale))
    assert hubd.idle_reap_due(root, {"agents": {}}, {}, now, started) is True


def test_hub_boot_command_platform_exe_policy(monkeypatch):
    monkeypatch.delenv(mailbox_mcp.HUB_CMD_ENV, raising=False)
    monkeypatch.setattr(mailbox_mcp.os, "name", "posix")
    default = mailbox_mcp.hub_boot_command()
    assert default[0] == mailbox_mcp.sys.executable and default[1].endswith("hub.py")
    monkeypatch.setenv(mailbox_mcp.HUB_CMD_ENV, "C:/tools/python.exe hub/hub.py")
    assert mailbox_mcp.hub_boot_command() is None
    monkeypatch.setattr(mailbox_mcp.os, "name", "nt")
    assert mailbox_mcp.hub_boot_command() == ["C:/tools/python.exe", "hub/hub.py"]


def test_touch_heartbeat_creates_and_refreshes(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    mailbox_mcp.touch_heartbeat()
    beat = tmp_path / paths.MCP_HEARTBEAT_FILE
    assert beat.exists()
    old = time.time() - 500.0
    os.utime(beat, (old, old))
    mailbox_mcp.touch_heartbeat()
    assert beat.stat().st_mtime > old
    monkeypatch.delenv("A2A_MAILBOX_ROOT")


def test_locate_win_accepts_native_drive_cwd(tmp_path):
    users = tmp_path / "Users"
    profile = users / "one"
    sessions = profile / ".codex" / "sessions" / "2026"
    sessions.mkdir(parents=True)
    bin_dir = profile / "AppData" / "Local" / "OpenAI" / "Codex" / "bin" / "abc"
    bin_dir.mkdir(parents=True)
    (bin_dir / "codex.exe").write_text("")
    thread = "aaaa5c8b-07a4-7f61-a73c-312c7a2d915e"
    rollout = sessions / f"rollout-2026-11-04T10-00-00-{thread}.jsonl"
    rollout.write_text('{"payload":{"cwd":"D:\\\\000-project"}}\n')
    found = codexq.locate_win("D:\\000-project", users_root=users)
    assert found == {
        "codex_bin": str(bin_dir / "codex.exe"),
        "codex_home": str(profile / ".codex"),
        "codex_thread": thread,
    }
    assert codexq.locate_win("/home/u/workspace", users_root=users) == {}


def test_queue_notifier_windows_falls_back_to_polling(tmp_path, monkeypatch):
    monkeypatch.setattr(queuenotify.os, "name", "nt")
    try:
        queuenotify.QueueNotifier(tmp_path)
        raised = False
    except OSError:
        raised = True
    assert raised


def test_paneless_online_accepts_unknown_cli_with_complete_anchors():
    bridge_record = {
        "cli": "unknown",
        "codex_bin": "/mnt/c/codex.exe",
        "codex_home": "/mnt/c/.codex",
        "codex_thread": "aaaa5c8b-07a4-7f61-a73c-312c7a2d915e",
    }
    assert hubd.paneless_online(bridge_record) is True
    assert hubd.paneless_online({"cli": "unknown"}) is False
    assert hubd.paneless_online({"cli": "claude", "spawn_cmd": None}) is False
