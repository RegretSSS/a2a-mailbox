#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUBLISH = ROOT / "scripts" / "publish.sh"


def lint() -> list[str]:
    if not PUBLISH.exists():
        return []
    problems = []
    source = PUBLISH.read_text()
    verify_line = ""
    for line in source.splitlines():
        if "VERIFY_PATTERN" in line and "grep" in line:
            verify_line = line
            break
    if not verify_line:
        return ["scripts/publish.sh: 找不到敏感词校验 grep 行"]
    if "-I" in verify_line:
        problems.append(
            "scripts/publish.sh: 校验 grep 禁用 -I(跳过二进制)——v13 事故实锤: .zcode/workflow-runs 的 .mjs "
            "编译产物带非文本字节, grep -I 当二进制跳过, 含 /home/user-a 真实路径穿透校验进公开仓暴露约一天"
        )
    if not re.search(r"grep\s+-\w*a", verify_line):
        problems.append("scripts/publish.sh: 校验 grep 必须 -a 强制文本模式扫二进制嫌疑文件")
    if "rm -rf .zcode" not in source:
        problems.append("scripts/publish.sh: 发布树必须排除 .zcode 守望 run 编译产物目录(事故复发面)")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
