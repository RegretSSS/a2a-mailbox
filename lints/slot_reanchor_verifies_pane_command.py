#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def lint() -> list[str]:
    problems = []
    tmuxio = (ROOT / "common" / "tmuxio.py").read_text()
    if "#{pane_current_command}" not in tmuxio.split("PANE_SNAPSHOT_FORMAT")[1].split("\n")[0]:
        problems.append("common/tmuxio.py PANE_SNAPSHOT_FORMAT 缺 pane_current_command 列, slot 重锚身份校验失去数据来源")
    if re.search(r"len\(parts\) != 6", tmuxio) is None:
        problems.append("common/tmuxio.py snapshot_all_panes 列数断言不是 6, 快照格式与解析器漂移")
    hub = (ROOT / "hub" / "hub.py").read_text()
    sweep = re.search(r"def sweep_liveness.*?(?=\ndef )", hub, re.S)
    if not sweep:
        return ["hub/hub.py: sweep_liveness 函数缺失"] + problems
    if "pane_commands_for" not in sweep.group(0):
        problems.append(
            "hub/hub.py sweep_liveness: slot 重锚未校验 pane_current_command 身份, 同名窗被陌生进程占用即错窗注入(C3)"
        )
    if "identity-mismatch" not in sweep.group(0):
        problems.append("hub/hub.py sweep_liveness: 身份不符拒绝重锚时缺 identity-mismatch 留痕")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
