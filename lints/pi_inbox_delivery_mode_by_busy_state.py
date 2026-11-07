#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXT = ROOT / "pi" / "a2a-inbox.ts"


def lint() -> list[str]:
    problems = []
    source = EXT.read_text()
    if 'deliverAs: "steer"' in source:
        problems.append(
            "pi/a2a-inbox.ts: 禁用 deliverAs=steer——主会话空闲(含仅 subagent 运行)时 steer 无目标回合被静默吞, "
            "sendUserMessage 不抛错且 rcpt 照写, hub 视角已送达实则 pi 永不上屏(aicontest 三封滞留+kit 02:33 悬案同根因)"
        )
    if 'pi.on("agent_start"' not in source or 'pi.on("agent_settled"' not in source:
        problems.append("pi/a2a-inbox.ts: 缺 agent_start/agent_settled 事件对维护 busy 标志——投递模式无法按忙闲分流")
    if 'deliverAs: "followUp"' not in source:
        problems.append("pi/a2a-inbox.ts: 忙时必须 followUp(排队待消费)——无 deliverAs 在 streaming 中会 throw, steer 会吞信")
    if "if (agentBusy) {" not in source:
        problems.append("pi/a2a-inbox.ts: takeMsg 未按 busy 分流——空闲态必须裸调 sendUserMessage 触发新回合(always triggers a turn)")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
