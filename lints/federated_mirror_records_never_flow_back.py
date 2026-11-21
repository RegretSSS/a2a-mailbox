#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FEDERATION = (ROOT / "common" / "federation.py").read_text(encoding="utf-8")


def lint() -> list[str]:
    problems = []
    if "if stamped:\n            continue" not in FEDERATION:
        problems.append(
            "common/federation.py: pull_peer 的 merge 闸不再跳过带章记录——"
            "远端持有的「本 peer 镜像」回流会覆盖本地档, 两侧互喂成拉锯"
            "(11-13 ab63ebb9 五连重演实案); 带任何 ssh_alias 章的远端记录必须一律跳过"
        )
    if 'mirrored["ssh_alias"] = alias' not in FEDERATION:
        problems.append(
            "common/federation.py: merge 进来的镜像档丢失 ssh_alias 盖章——"
            "无章镜像会被 sweep 当本地档处理, paneless TTL 与 offline 广播全部失准"
        )
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
