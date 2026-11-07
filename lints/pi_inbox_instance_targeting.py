#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXT = ROOT / "pi" / "a2a-inbox.ts"
DEPLOY_TARGET = Path.home() / ".pi" / "agent" / "extensions" / "a2a-inbox.ts"


def lint() -> list[str]:
    problems = []
    source = EXT.read_text()
    if "instancePanes(rec).includes(pane)" not in source:
        problems.append("pi/a2a-inbox.ts: resolveAgentId 未查 instances 表——主锚被后注册实例覆盖后, 先注册实例只能靠 cwd 兜底解析, 同目录多 pi 档即歧义断信")
    if "targetedAtOtherInstance(envelope, process.env.TMUX_PANE" not in source:
        problems.append("pi/a2a-inbox.ts: takeMsg 未按 to_instance 过滤——@定向信落共享信箱被任意实例抢收, 定向语义在 native 通道失效")
    if not re.search(r"\.map\([^;]*\)\s*\n\s*\.filter\(Boolean\)", source):
        problems.append("pi/a2a-inbox.ts: instancePanes 链式调用断裂(分号截断)——实例 pane 列表恒空")
    if DEPLOY_TARGET.exists():
        try:
            deployed = DEPLOY_TARGET.read_text()
        except OSError:
            deployed = ""
        if deployed and deployed != source:
            problems.append("pi/a2a-inbox.ts: 本机 ~/.pi/agent/extensions 副本滞后——E2E 会跑在旧消费逻辑上, 先重新部署 extension")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
