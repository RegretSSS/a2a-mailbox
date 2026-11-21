#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def lint() -> list[str]:
    problems = []
    source = (ROOT / "common" / "detect.py").read_text()
    body = re.search(r"def build_agent_id.*?(?=\ndef )", source, re.S)
    if not body:
        return ["common/detect.py: build_agent_id 函数缺失"]
    if "host_qualifier()" not in body.group(0):
        problems.append(
            "common/detect.py build_agent_id: 裸 hostname 做 host 段会在多主机同名(如都是 localhost)时碰撞出同 id, 必须经 host_qualifier()"
        )
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
