#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HUBKEEP = ROOT / "common" / "hubkeep.py"


def lint() -> list[str]:
    problems = []
    source = HUBKEEP.read_text()
    if "start_new_session=True" not in source:
        problems.append(
            "common/hubkeep.py: hub spawn 必须 start_new_session=True——MCP(A)拉起的 hub 被 B/C 共用, "
            "不脱离会话组则 A 退出时级联 SIGHUP 带走 hub, 其他 agent 全断投递"
        )
    if "stdin=subprocess.DEVNULL" not in source or "stdout=subprocess.DEVNULL" not in source or "stderr=subprocess.DEVNULL" not in source:
        problems.append("common/hubkeep.py: hub spawn 三流必须 DEVNULL——继承 MCP 的 stdio 管道会把 hub 输出灌进 MCP 协议流")
    if "close_fds=True" not in source:
        problems.append("common/hubkeep.py: hub spawn 必须 close_fds=True——泄漏的 fd 会钉住已退出进程的资源")
    ensure = source.split("def ensure_hub_running", 1)[-1].split("def ", 1)[0]
    order = ensure.index("hub_pids()") if "hub_pids()" in ensure else -1
    systemd_probe = ensure.index('["cat", SYSTEMD_UNIT') if '["cat", SYSTEMD_UNIT' in ensure else -1
    spawn = ensure.index("subprocess.Popen") if "subprocess.Popen" in ensure else -1
    if not (0 <= order < systemd_probe < spawn):
        problems.append(
            "common/hubkeep.py: ensure 顺序必须 判活→systemd cat→start→detached spawn——"
            "先 spawn 会与 systemd 双实例, 只 systemd 会让无 systemd 环境裸奔"
        )
    if '"is-active", "--quiet", SYSTEMD_UNIT' not in ensure:
        problems.append(
            "common/hubkeep.py: systemctl start 后必须 is-active 复查——start rc 不可信"
            "(stop 收尾窗口/start 撞收尾均可能静默不成), 不复查不回落 spawn 会假 True"
        )
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
