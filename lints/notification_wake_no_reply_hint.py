#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from common import msgfmt

NOTIFICATION_BODIES = (
    "E2E-V2 通知腿: 纯通知无需回函, 读 DESIGN.md『E2E-V2』后安静即可",
    "部署完成纯通知",
)


def lint() -> list[str]:
    problems = []
    for body in NOTIFICATION_BODIES:
        wake = msgfmt.compose_wake("alice", "m1", body)
        if "[需回函]" in wake or "mail_send" in wake:
            problems.append(
                f"通知类 body(expect_reply 默认 False)不得携带任何回函尾缀——"
                "与『无需回函』正文明示自相矛盾, 收件 agent 照尾句回函会破坏通知腿语义"
                "(hub WAIT_CONFIRM 超时 close_unconfirmed 才是通知的合法终态)"
            )
        parsed = msgfmt.parse_wake(wake)
        if parsed is None or parsed[3] != body:
            problems.append(f"parse_wake 往返失真: {body!r} -> {parsed}")
    task_wake = msgfmt.compose_wake("alice", "m2", "回函一句确认", expect_reply=True)
    if not task_wake.endswith(msgfmt.REPLY_TAG):
        problems.append("expect_reply=True 必须以『[需回函]』短标记收尾(不复述地址, from=/id= 头部已有)")
    task_parsed = msgfmt.parse_wake(task_wake)
    if task_parsed is None or task_parsed[3] != "回函一句确认":
        problems.append(f"expect_reply=True 的 parse_wake 往返失真: {task_parsed}")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
