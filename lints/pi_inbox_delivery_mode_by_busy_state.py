#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXT = ROOT / "pi" / "a2a-inbox.ts"


def lint() -> list[str]:
    problems = []
    source = EXT.read_text()
    if "sendUserMessage(wakeText).then(" in source or "sendUserMessage(wakeText, { deliverAs: \"steer\" }).then(" in source:
        problems.append(
            "pi/a2a-inbox.ts: 禁止对 pi.sendUserMessage 链 .then——本版 pi 的 ExtensionAPI 包装器(agent-session.js:2792 无 return)返回 undefined, "
            "undefined.then 一调用即 TypeError 崩掉整个 agent(11-07 15:24 pi-aicontest 崩溃根因, 三折拉回); "
            "类型面双定义: session 层 Promise<void> 是内部实现, ExtensionAPI 本体是 void, 以 runtime 实测为准"
        )
    if "agentBusy" in source or 'pi.on("agent_start"' in source:
        problems.append(
            "pi/a2a-inbox.ts: 禁止自维护 busy 标志分流——agent_start/settled 事件对被 workflow 长回合污染恒 busy, "
            "信全数饿死 followUp 队列; 且用户手打字永远优先于 followUp(两级队列), 排队通道结构性劣后"
        )
    if 'pi.sendUserMessage(wakeText, { deliverAs: "steer" });' not in source:
        problems.append(
            "pi/a2a-inbox.ts: 投递必须是单一形态 deliverAs=steer——源码 prompt() 两分支皆安全: "
            "idle 时 streamingBehavior 被忽略走正常提交(立即触发回合), streaming 时 steer 进打断队列(与用户手打字同级); "
            "裸调(无 deliverAs)在 streaming 中被包装器 .catch 吞成 emitError=静默丢信且 rcpt 已写假送达"
        )
    if "try {\n      pi.sendUserMessage" not in source:
        problems.append("pi/a2a-inbox.ts: sendUserMessage 必须同步 try-catch 包裹——运行时未就绪桩同步 throw, 捕获后清 inflight 留队重扫, 不捕获则 pi 退出(PI_EXIT=1 重启循环)")
    if "rescuer = setInterval(scanQueue" not in source:
        problems.append(
            "pi/a2a-inbox.ts: 必须有周期幂等重扫(setInterval(scanQueue))——fs.watch 丢事件/加载期未就绪遗留的信靠它兜底, 5s 量级"
        )
    if "followUp" in source:
        problems.append("pi/a2a-inbox.ts: 禁用 followUp——两级队列里恒劣后于用户手打字, 长回合场景永饿死(11-07 三封滞留案)")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
