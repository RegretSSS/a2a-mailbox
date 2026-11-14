#!/usr/bin/env python3
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "lints"}
SHADOWED = "mcp"


def violations_of(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        else:
            continue
        for name in names:
            if name.split(".")[0] == SHADOWED:
                found.append(
                    f"{path}:{node.lineno}: import {name} 会解析到 PyPI 的 mcp 包"
                    f"（fastmcp 依赖），不是本仓库 mcp/ 目录——按文件路径 importlib 加载"
                )
    return found


def main() -> int:
    violations = []
    for path in sorted(ROOT.rglob("*.py")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        violations.extend(violations_of(path))
    if (ROOT / SHADOWED / "__init__.py").exists():
        violations.append(
            "mcp/__init__.py: 目录一旦成 regular package 就真正遮蔽 PyPI 的 mcp 包"
            "（fastmcp 依赖）——现状靠 namespace package 让位 regular 的导入规则才安全, 必须保持无 __init__"
        )
    for line in violations:
        print(line)
    if violations:
        print(f"no_shadowed_mcp_import: {len(violations)} 处违规")
        return 1
    print("no_shadowed_mcp_import: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
