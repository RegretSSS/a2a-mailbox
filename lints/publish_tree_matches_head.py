#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUBLISH_SH = ROOT / "scripts" / "publish.sh"


def lint() -> list[str]:
    if not PUBLISH_SH.exists():
        return []
    source = PUBLISH_SH.read_text(encoding="utf-8")
    problems = []
    if "status --porcelain" not in source:
        problems.append(
            "scripts/publish.sh: 缺脏树闸——出包检 git HEAD, 工作树未提交改动会静默丢失"
            "(v0.2.0 tar 旧树实案: 先跑包后提交, 实包三证全旧); "
            "clone 前必须: git -C $SRC_ROOT status --porcelain 非空即 abort"
        )
    if ".release-info" not in source:
        problems.append(
            "scripts/publish.sh: 缺 .release-info 指纹文件——no-.git tar 无 git 身份, "
            "终检只能内容抽查无法指纹对指纹; 检出后必须写 source_sha+built_at 进包"
        )
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
