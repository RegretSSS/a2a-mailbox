#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FED = ROOT / "common" / "federation.py"


def lint() -> list[str]:
    problems = []
    source = FED.read_text()
    pull_peer = source.split("def pull_peer", 1)[-1].split("def pull_all", 1)[0]
    if "registry.upsert" in pull_peer:
        problems.append(
            "common/federation.py: pull_peer 禁逐条 registry.upsert——每次都是锁+全量 load+save, "
            "远端 N 档=N 次串行锁竞争; 必须攒 dict 后 apply_batch 一次落盘(N 锁→1 锁)"
        )
    if "apply_batch" not in pull_peer:
        problems.append("common/federation.py: pull_peer 合并必须走 registry.apply_batch 批量接口")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
