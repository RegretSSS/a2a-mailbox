#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUBPROCESS_RUN = re.compile(r"subprocess\.run\(")


def lint() -> list[str]:
    problems = []
    targets = [ROOT / "hub" / "hub.py"] + sorted((ROOT / "scripts").glob("*.py"))
    for path in targets:
        lines = path.read_text().split("\n")
        for index, line in enumerate(lines):
            if not SUBPROCESS_RUN.search(line):
                continue
            window = "\n".join(lines[index:index + 12])
            if "timeout=" not in window:
                problems.append(
                    f"{path.relative_to(ROOT)}:{index + 1}: subprocess.run 必须带 timeout——"
                    "hub 主循环是 2s 扫描周期, 无超时的外部命令(notify/spawn/interop)会卡死整个投递面"
                )
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
