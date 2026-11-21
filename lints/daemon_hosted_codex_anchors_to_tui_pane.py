#!/usr/bin/env python3
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DAEMON_MISANCHORED_PANE = "%11"
DAEMON_MISANCHORED_PID = "2485588"
TUI_PANE = "%51"
TUI_PID = "2269702"
TUI_THREAD = "aaaa5c8b-07a4-7f61-a73c-312c7a2d915e"
TUI_SLOT = "codex-q"


def load_mcp():
    spec = importlib.util.spec_from_file_location("mailbox_mcp", ROOT / "mcp" / "mailbox_mcp.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def seed(mcp, workspace, tui_found):
    os.environ["A2A_MAILBOX_ROOT"] = workspace
    os.environ["CODEX_HOME"] = workspace
    os.environ.pop("TMUX_PANE", None)
    mcp.paths.mailbox_root = lambda: Path(workspace)
    mcp.detect.detect_cli = lambda: "codex"
    mcp.detect.current_pane_id = lambda: DAEMON_MISANCHORED_PANE
    mcp.detect.local_host = lambda: "host-a"
    mcp.detect.tailnet_host = lambda: ""
    mcp.spawn_cmd_from_env = lambda: None
    mcp.ssh_alias_from_env = lambda: ""
    mcp.boot_hub_if_absent = lambda root: None
    mcp.shutil.which = lambda name: "/usr/local/bin/codex"
    mcp.codexq.thread_from_ancestors = lambda: ""
    mcp.codexq.locate_tui = lambda cwd: tui_found

    def pane_pid(pane, ssh=None):
        return TUI_PID if pane == TUI_PANE else (DAEMON_MISANCHORED_PID if pane else "")

    mcp.tmuxio.pane_pid = pane_pid
    mcp.tmuxio.pane_slot = lambda pane, ssh=None: TUI_SLOT if pane == TUI_PANE else "web"
    mcp.tmuxio.pane_window_name = lambda pane, ssh=None: TUI_SLOT if pane == TUI_PANE else "web"
    mcp.tmuxio.pane_pid_matches = lambda pane, pid, ssh=None: bool(pane) and pid in (TUI_PID, DAEMON_MISANCHORED_PID)
    return Path(workspace)


def lint() -> list[str]:
    problems = []
    mcp = load_mcp()
    tui_found = {"pane_id": TUI_PANE, "pane_pid": TUI_PID, "thread": TUI_THREAD}
    seed(mcp, tempfile.mkdtemp(prefix="a2a-lint-"), tui_found)
    record = mcp.register_record()
    if record.get("pane_id") != TUI_PANE or record.get("pane_pid") != TUI_PID or record.get("slot") != TUI_SLOT:
        problems.append(
            "codex 锚定错窗: daemon 代管模式下 MCP 祖先链到 app-server 即断, current_pane_id 反查错锚 mgw:web(%11)——"
            "实测 2026-11-04 codex-host-a-a2a-mailbox 注册 pane=%11/thread=None, "
            "queue 投递因 thread 缺失降级 tmux 且 degrade 会注入 magpie 网关窗; "
            "必须用 locate_tui 反锚真正的 TUI pane"
        )
    if record.get("codex_thread") != TUI_THREAD:
        problems.append("codex 锚定丢 thread: TUI pane cmdline 带 resume <uuid>, 反锚后 codex_thread 必须落盘")
    if "codex_pane_id" in record:
        problems.append("codex 锚定泄漏: codex_pane_id 是内部覆盖字段, 不得残留在 registry 记录")

    seed(mcp, tempfile.mkdtemp(prefix="a2a-lint-"), {})
    record2 = mcp.register_record()
    if record2.get("codex_thread"):
        problems.append("codex 锚定捏造: locate_tui 无唯一命中时不得凭空写 thread")
    if record2.get("pane_id") != DAEMON_MISANCHORED_PANE:
        problems.append("codex 锚定盲改: locate 失败时保持既有 pane 锚, 不得换窗")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
