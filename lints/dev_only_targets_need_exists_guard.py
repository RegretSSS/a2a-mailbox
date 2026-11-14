#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LINTS = ROOT / "lints"
DEV_ONLY_FRAGMENTS = (
    '/ "publish.sh"',
    '/ "DESIGN.md"',
    '/ "E2E-REPORT.md"',
    '/ "E2E-V2-REPORT.md"',
    '/ "publish"',
)


def lint() -> list[str]:
    problems = []
    for path in sorted(LINTS.glob("*.py")):
        source = path.read_text()
        for fragment in DEV_ONLY_FRAGMENTS:
            if fragment in source and ".exists()" not in source:
                problems.append(
                    f"{path.name}: 读取 dev-only 目标({fragment.strip()})必须 .exists() 自守卫——"
                    "公开树无此文件(publish.sh 发布前自删), 无守卫的 lint 在公开仓 CI 必炸"
                    "(v15 实锤: publish_verify_scans_binary_text 曾令 CI 红, zcode 热修 b5dc1c3)"
                )
                break
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
