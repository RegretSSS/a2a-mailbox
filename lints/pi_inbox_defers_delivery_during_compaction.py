#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXTENSION = ROOT / "pi" / "a2a-inbox.ts"


def lint() -> list[str]:
    problems = []
    if not EXTENSION.exists():
        return ["pi/a2a-inbox.ts: pi 扩展缺失——pi-native 通道无认领方"]
    source = EXTENSION.read_text(encoding="utf-8")
    if "let compacting = false" not in source:
        problems.append(
            "pi/a2a-inbox.ts: 缺 compacting 状态位——compact 进行中 pi 的 steer 注入会丢信,"
            " takeMsg 必须在 compacting 时不认领(信留 queue, compact 完 rescuer/watch 补投)"
        )
    for event in ("session_before_compact", "session_compact", "session_compact_failed"):
        if f'"{event}"' not in source:
            problems.append(
                f'pi/a2a-inbox.ts: 缺 "{event}" 订阅——compacting 标志的置位/复位依赖完整三事件,'
                " session_compact_failed 不复位会把 pi 永久闸死"
            )
    if "|| compacting" not in source:
        problems.append(
            "pi/a2a-inbox.ts: takeMsg 缺 compacting 闸——认领(rcpt 写盘)必须与注入同闸,"
            " 只闸注入不闸认领会让信被认领后丢失"
        )
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
