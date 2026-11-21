#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def lint() -> list[str]:
    problems = []
    hub = (ROOT / "hub" / "hub.py").read_text()
    collect = re.search(r"def collect_queue_daemon.*?(?=\n    def )", hub, re.S)
    if not collect:
        return ["hub/hub.py: collect_queue_daemon 函数缺失"]
    if "degrade_native" in collect.group(0):
        problems.append(
            "hub/hub.py collect_queue_daemon: queue 通道失败走 degrade_native 回退 tmux, 空 pane 会 send-keys 落当前活动窗(A 族错窗键入)"
        )
    if "retry_or_giveup" not in collect.group(0):
        problems.append("hub/hub.py collect_queue_daemon: 失败必须走 retry_or_giveup 滞留重试链")
    dispatch_calls = re.findall(r"(?<!not )(?<=\.)dispatch_queue_daemon\(", hub)
    guarded = re.findall(r"not\s+\S+\.dispatch_queue_daemon\(", hub)
    if len(dispatch_calls) != len(guarded):
        problems.append(
            "hub/hub.py: dispatch_queue_daemon 返回 bool 的调用点未全部消费返回值, Popen 失败仍注册 delivery 会空转等回执"
        )
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
