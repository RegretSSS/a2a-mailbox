#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWED = ("common/lockfile.py",)


def lint() -> list[str]:
    problems = []
    for path in sorted(ROOT.glob("**/*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = str(path.relative_to(ROOT))
        if rel.startswith(("tests/", "lints/")) or rel in ALLOWED or not rel.endswith(".py"):
            continue
        if "import fcntl" in path.read_text():
            problems.append(
                f"{rel}: 直接 import fcntl——纯 Windows 节点 import 即炸, 文件锁必须走 common/lockfile 平台抽象"
            )
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
