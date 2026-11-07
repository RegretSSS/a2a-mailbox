#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "lints", "tests"}
MARK = "capture-pane"
ALLOWED = "common/tmuxio.py"


def main() -> int:
    violations = []
    for path in sorted(ROOT.rglob("*.py")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        owner = path.relative_to(ROOT).as_posix() == ALLOWED
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            if MARK in line and not owner:
                violations.append(
                    f"{path}:{number}: capture-pane 只允许出现在 {ALLOWED} 的取证函数里——"
                    "屏幕形态不能参与状态判定（compactme v0.2.x 四次生产事故根源）"
                )
    for line in violations:
        print(line)
    if violations:
        print(f"capture_pane_forensics_only: {len(violations)} 处违规")
        return 1
    print("capture_pane_forensics_only: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
