#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def lint() -> list[str]:
    problems = []
    path = ROOT / "hub" / "hub.py"
    for index, line in enumerate(path.read_text().splitlines(), start=1):
        if "subprocess.run" in line:
            problems.append(
                f"hub/hub.py:{index}: hub 进程内禁 subprocess.run——notify(≤8s)/spawn(≤600s) 会卡死主循环 tick,"
                f" 一律 Popen+poll 收割: {line.strip()}"
            )
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
