#!/usr/bin/env python3
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "lints", "tests"}
APPEND_MODES = {"a+", "a+ b"}


def violations_of(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        opens = [
            call for call in ast.walk(node)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "open"
            and any(
                isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value in APPEND_MODES
                for arg in call.args[1:]
            )
        ]
        if not opens:
            continue
        seeks = [
            call for call in ast.walk(node)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "seek"
        ]
        if not seeks:
            line = opens[0].lineno
            found.append(f"{path}:{line}: a+ 模式初始读位置在文件尾，read 前必须 seek(0)")
    return found


def main() -> int:
    violations = []
    for path in sorted(ROOT.rglob("*.py")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        violations.extend(violations_of(path))
    for line in violations:
        print(line)
    if violations:
        print(f"append_mode_read_needs_seek: {len(violations)} 处违规")
        return 1
    print("append_mode_read_needs_seek: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
