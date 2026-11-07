#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "snippets" / "zcode-watch-skill" / "template.dwf.ts"


def lint() -> list[str]:
    problems = []
    source = TEMPLATE.read_text()
    seq_match = re.search(r"seq 1 (\d+)", source)
    timeout_match = re.search(r"timeoutMs: (\d+)", source)
    round_match = re.search(r"round <= (\d+)", source)
    if not seq_match or not timeout_match or not round_match:
        return ["snippets/zcode-watch-skill/template.dwf.ts: 解析不出 seq 轮数/timeoutMs/外层轮数(模板结构变了请人工核对)"]
    inner_loops = int(seq_match.group(1))
    timeout_ms = int(timeout_match.group(1))
    outer_rounds = int(round_match.group(1))
    if outer_rounds > 60:
        problems.append(f"template.dwf.ts: 外层 {outer_rounds} 轮超引擎上限 60")
    inner_seconds = inner_loops * 5
    headroom_seconds = timeout_ms / 1000 - inner_seconds
    if headroom_seconds < 900:
        problems.append(
            f"template.dwf.ts: 死亡配置——内窗 {inner_loops}x5s={inner_seconds}s 逼近 timeoutMs {timeout_ms/1000:g}s"
            f"(余量仅 {headroom_seconds:g}s)。内窗必须 2700x5s 级并留 >=15 分钟(900s)余量: "
            "安静满窗时内窗先自然超时退出(exit 42 续轮), 顶到 timeoutMs 会熔断整个 run(11-05 实测事故, v15 前公开仓原样带病)"
        )
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
