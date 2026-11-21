#!/usr/bin/env python3
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "lints", "tests"}
HOT_PREFIXES = ("tick", "inject", "clear", "send", "paste", "pane")
WATCHED_FILES = ("hub/hub.py", "common/tmuxio.py")
CONTAINER_NODES = (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp)


def violations_of(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if not node.name.startswith(HOT_PREFIXES):
            continue
        for child in ast.walk(node):
            if isinstance(child, CONTAINER_NODES):
                found.append(
                    f"{path}:{child.lineno}: 热路径函数 {node.name}() 内出现容器字面量——"
                    "提升为模块级常量或复用已有对象（乱分配导致碎片）"
                )
    return found


def main() -> int:
    violations = []
    for relative in WATCHED_FILES:
        path = ROOT / relative
        if path.exists():
            violations.extend(violations_of(path))
    for line in violations:
        print(line)
    if violations:
        print(f"hot_path_container_literals: {len(violations)} 处违规")
        return 1
    print("hot_path_container_literals: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
