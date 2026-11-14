#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXT = ROOT / "pi" / "a2a-inbox.ts"


def lint() -> list[str]:
    problems = []
    source = EXT.read_text()
    claim = 'const handle = fs.openSync(rcpt, "wx");'
    inject = 'pi.sendUserMessage(wakeText, { deliverAs: "steer" });'
    claim_at = source.find(claim)
    inject_at = source.find(inject)
    if claim_at < 0:
        problems.append("pi/a2a-inbox.ts: 缺 rcpt wx 认领——多消费实例并发下无互斥")
    elif inject_at < 0:
        problems.append("pi/a2a-inbox.ts: 缺 steer 注入调用")
    elif claim_at > inject_at:
        problems.append(
            "pi/a2a-inbox.ts: 认领必须先于注入——rcpt 的 openSync(wx) 排在 sendUserMessage 之后时, "
            "existsSync 检查与 wx 写之间夹着整个注入调用, 同档并发实例(main+workflow subagent 同 cwd 认领同档) "
            "全部通过检查各自注入自己会话: 一封信扇出 N 份(subagent 全员收信+多份回信, 2026-11-12 jzx→pi-aicontest 案)"
        )
    rollback = "fs.unlinkSync(rcpt)"
    catch_after_inject = source.find("} catch", inject_at)
    if rollback not in source[catch_after_inject:catch_after_inject + 400]:
        problems.append(
            "pi/a2a-inbox.ts: 认领后注入失败必须 unlink 回滚 rcpt——不回滚则失败终态留下 rcpt, "
            "其它实例见 rcpt 存在永不重试, 信滞留至 unconfirmed(11-07 契约: 失败态 rcpt 不在)"
        )
    if "process.pid" not in source:
        problems.append("pi/a2a-inbox.ts: rcpt 应记 pid——认领者取证(极端 crash 残留认领时定位归属)")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
