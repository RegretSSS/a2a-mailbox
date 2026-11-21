#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "lints", "tests"}
NAMED_KEYS = ("Enter", "BSpace")


def violations_of(path: Path) -> list[str]:
    violations = []
    for number, line in enumerate(path.read_text().splitlines(), start=1):
        if "send-keys" not in line:
            continue
        literal_safe = "-l" in line
        lowered = line.lower()
        named_key_safe = any(key.lower() in lowered for key in NAMED_KEYS)
        if not literal_safe and not named_key_safe:
            violations.append(
                f"{path}:{number}: send-keys 不带 -l 会把文本按键名解释"
                "（compactme 实测事故面），字面注入必须 -l；具名键仅允许 {'Enter', 'BSpace'}"
            )
    return violations


def main() -> int:
    violations = []
    for path in sorted(ROOT.rglob("*.py")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        violations.extend(violations_of(path))
    for line in violations:
        print(line)
    if violations:
        print(f"send_keys_requires_literal_flag: {len(violations)} 处违规")
        return 1
    print("send_keys_requires_literal_flag: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
