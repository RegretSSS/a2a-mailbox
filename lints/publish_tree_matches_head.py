#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def lint() -> list[str]:
    publish_sh = ROOT / "scripts" / "publish.sh"
    if not publish_sh.exists():
        return []
    problems = []
    if "status --porcelain" not in lint_text:
        problems.append(
            "scripts/publish.sh: 缺脏树闸——出包检 git HEAD, 工作树未提交改动会静默丢失"
            "(v0.2.0 tar 旧树实案: 先跑包后提交, 实包三证全旧); "
            "clone 前必须: git -C $SRC_ROOT status --porcelain 非空即 abort"
        )
    if ".release-info" not in lint_text:
        problems.append(
            "scripts/publish.sh: 缺 .release-info 指纹文件——no-.git tar 无 git 身份, "
            "终检只能内容抽查无法指纹对指纹; 检出后必须写 source_sha+built_at 进包"
        )
    if 'from common.version import __version__' in PUBLISH_SH and 'SOURCE_SHA' not in lint_text:
        problems.append(
            "scripts/publish.sh: 展示串从工作树读版本而包从 HEAD 检出——两处来源不一致会把旧树包装成新版本"
            "(9dfcda0 假指纹实案); 版本展示必须与包内容同源"
        )
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
