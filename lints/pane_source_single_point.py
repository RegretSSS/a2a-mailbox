#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "lints", "tests"}
MARK = "TMUX_PANE"
ALLOWED = "common/detect.py"


def main() -> int:
    violations = []
    for path in sorted(ROOT.rglob("*.py")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        owner = path.relative_to(ROOT).as_posix() == ALLOWED
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            if MARK in line and not owner:
                violations.append(
                    f"{path}:{number}: TMUX_PANE 只允许在 {ALLOWED} 读——"
                    "MCP stdio 客户端（python-sdk get_default_environment 白名单）会清洗环境变量，"
                    "pane 锚点必须走 detect.current_pane_id 的进程树反查兜底"
                )
    for line in violations:
        print(line)
    if violations:
        print(f"pane_source_single_point: {len(violations)} 处违规")
        return 1
    print("pane_source_single_point: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
