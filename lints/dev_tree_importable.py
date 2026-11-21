#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = ("common", "mcp", "hub", "lints", "scripts")
SCAN_FILES = ()


def python_sources():
    for dirname in SCAN_DIRS:
        for path in sorted((ROOT / dirname).rglob("*.py")):
            yield path
    for name in SCAN_FILES:
        path = ROOT / name
        if path.exists():
            yield path


def display(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def lint() -> list[str]:
    problems = []
    seen = False
    for path in python_sources():
        seen = True
        try:
            source = path.read_text()
        except OSError as exc:
            problems.append(f"{display(path)}: 不可读({exc})——外部直调方会被挡")
            continue
        try:
            compile(source, str(path), "exec")
        except SyntaxError as exc:
            problems.append(f"{display(path)}: SyntaxError line {exc.lineno}——半成品窗口, 直调方(zcode 哨兵/发布复验/运维脚本)全断")
    if not seen:
        problems.append(f"扫描范围 {SCAN_DIRS} 为空——树布局漂移, importable 保底失效")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
