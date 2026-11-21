#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FEDERATION = (ROOT / "common" / "federation.py").read_text(encoding="utf-8")
REGISTRY = (ROOT / "common" / "registry.py").read_text(encoding="utf-8")


def lint() -> list[str]:
    problems = []
    if "tombstone_at" not in FEDERATION:
        problems.append(
            "common/federation.py: pull_peer 无本地墓碑闸——apply_batch 是 upsert-only,"
            " 本地 sweep 已剔除的档会被远端快照无脑复活再剔再复活(拉锯另一腿); "
            "merge 前必须 tombstone_at 判死"
        )
    if "write_tombstone" not in REGISTRY.split("def forget")[1].split("\ndef ")[0]:
        problems.append(
            "common/registry.py: forget 不写墓碑——剔除事实没有传播载体,"
            " pull 复活闸无从判定; forget 删除成功后必须 write_tombstone"
        )
    if "clear_tombstone" not in REGISTRY.split("def touch")[1].split("\ndef ")[0]:
        problems.append(
            "common/registry.py: touch 不清墓碑——真档复活续命后墓碑残留,"
            " 下次合法 merge 会被陈旧墓碑误挡; touch 成功后必须 clear_tombstone"
        )
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
