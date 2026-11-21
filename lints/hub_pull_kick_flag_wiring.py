#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HUB = ROOT / "hub" / "hub.py"


def lint() -> list[str]:
    problems = []
    source = HUB.read_text()
    if "FED_PULL_NOW_FILENAME" not in source:
        problems.append("hub/hub.py: 缺 fed-pull-now 旗标常量——http /kick 直投后无法即时拉取, 跨机信仍要盲等 60s 周期")
    if "kick_flag.unlink" not in source or "last_pull = 0.0" not in source:
        problems.append("hub/hub.py: 旗标消费必须 unlink+清零 last_pull——漏 unlink 则每循环重拉, 漏清零则踢一脚不生效")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
