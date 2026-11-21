#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def lint() -> list[str]:
    problems = []
    source = (ROOT / "common" / "registry.py").read_text()
    touch_body = re.search(r"def touch.*?(?=\ndef )", source, re.S)
    if not touch_body:
        return [f"common/registry.py: touch 函数缺失"]
    body = touch_body.group(0)
    if "agents.get(agent_id, {})" in body or re.search(r"agents\[agent_id\] = (?!existing)", body):
        problems.append(
            "common/registry.py touch: 对未知 agent 造桩记录会随联邦扩散成无锚点脏数据, touch 只许刷新在册记录"
        )
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
