#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXT = ROOT / "pi" / "a2a-inbox.ts"


def lint() -> list[str]:
    problems = []
    source = EXT.read_text()
    if "const holderByAgent" not in source.split("export default")[0]:
        problems.append(
            "pi/a2a-inbox.ts: holderByAgent 必须在模块顶层——pi 扩展 factory 被缓存而顶层状态跨会话实例共享, "
            "放进 default() 闭包则每实例一份, 主会话独占失效"
        )
    if 'if (holderByAgent[agentId] === "alive") {\n      return;\n    }' not in source:
        problems.append(
            "pi/a2a-inbox.ts: 认领档时 holder 在岗必须静默 return——fork 槽实例(同 cwd 同 pane 认领同档)任何消费动作"
            "(watcher/heartbeat/rescuer)都绕过主会话独占, 2026-11-12 jzx→pi-aicontest 扇出案同族"
        )
    if 'holderByAgent[agentId] = "alive";' not in source or "iHold = true;" not in source:
        problems.append("pi/a2a-inbox.ts: 持有权必须由首达实例置 alive 并记 iHold")
    if 'holderByAgent[agentId] = "dead";' not in source or "if (iHold && agentId)" not in source:
        problems.append(
            "pi/a2a-inbox.ts: session_shutdown 必须仅由持有者(iHold)交班置 dead——无 iHold 判据则 fork 槽收尾会把主会话的锁错杀, "
            "主会话存活期间锁不弃(用户设计: 主会话不被关闭永不弃锁)"
        )
    start_watching = source.split("function startWatching")[1].split("\n  }")[0] if "function startWatching" in source else ""
    if "rescuer = setInterval" not in start_watching:
        problems.append(
            "pi/a2a-inbox.ts: rescuer(周期重扫)必须在 startWatching 内启动——模块加载级启动会让静默实例也持有重扫通道绕过独占"
        )
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
