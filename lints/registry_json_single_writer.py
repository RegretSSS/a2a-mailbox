#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "lints", "tests"}
LITERAL = "registry.json"
LITERAL_OWNER = "common/paths.py"
REQUIRED_WRITE_CALL = "atomicio.write_json_atomic"
WRITE_OWNER = "common/registry.py"


def main() -> int:
    violations = []
    for path in sorted(ROOT.rglob("*.py")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        owner = path.relative_to(ROOT).as_posix() == LITERAL_OWNER
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            if LITERAL in line and not owner:
                violations.append(f"{path}:{number}: registry.json 字面量只允许出现在 {LITERAL_OWNER}")
    writer = ROOT / WRITE_OWNER
    if REQUIRED_WRITE_CALL not in writer.read_text():
        violations.append(f"{WRITE_OWNER}: 注册表写入必须经过 {REQUIRED_WRITE_CALL}（tmp+replace 原子替换）")
    for line in violations:
        print(line)
    if violations:
        print(f"registry_json_single_writer: {len(violations)} 处违规")
        return 1
    print("registry_json_single_writer: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
