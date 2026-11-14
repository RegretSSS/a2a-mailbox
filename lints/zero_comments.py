#!/usr/bin/env python3
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache"}


def python_violations(path: Path) -> list[str]:
    found = []
    with path.open("rb") as handle:
        for token in tokenize.tokenize(handle.readline):
            if token.type == tokenize.COMMENT and token.start[0] > 1:
                found.append(f"{path}:{token.start[0]}: {token.string}")
    return found


def shell_violations(path: Path) -> list[str]:
    found = []
    for number, line in enumerate(path.read_text().splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#") and number != 1:
            found.append(f"{path}:{number}: {stripped}")
    return found


def main() -> int:
    violations = []
    for path in sorted(ROOT.rglob("*")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if not path.is_file():
            continue
        if path.suffix == ".py":
            violations.extend(python_violations(path))
        elif path.suffix == ".sh":
            violations.extend(shell_violations(path))
    for line in violations:
        print(line)
    if violations:
        print(f"zero_comments: {len(violations)} 处注释违规（想写注释 = 命名不够好，去改名）")
        return 1
    print("zero_comments: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
