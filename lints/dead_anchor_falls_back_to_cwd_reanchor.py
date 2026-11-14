#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HUB = ROOT / "hub" / "hub.py"


def lint() -> list[str]:
    problems = []
    fn = HUB.read_text().split("def reanchor_cwd_panes", 1)
    if len(fn) < 2:
        return ["hub/hub.py: reanchor_cwd_panes 不存在——cwd 回锚入口失踪"]
    body = fn[1].split("\ndef ", 1)[0]
    if 'if record.get("pane_id")' in body:
        problems.append(
            "hub/hub.py: reanchor_cwd_panes 禁止『有 pane_id 即跳过』——档锚指向已消亡 pane 时(实验窗关闭/respawn 换窗)"
            "回锚永不发生, 档卡死离线停投(host-b blobtest 污染案根因之一); 必须查快照判活, 死锚继续走 cwd 唯一命中"
        )
    if 'pane_id in snap["panes"]' not in body:
        problems.append(
            "hub/hub.py: reanchor_cwd_panes 必须以 pane_id in snap[\"panes\"] 判锚存活——活锚跳过, 死锚/无锚进 cwd 匹配"
        )
    if "死锚重锚" not in body:
        problems.append("hub/hub.py: 死锚回锚日志必须区分『死锚重锚』与普通 cwd 匹配回锚——离线取证要能定位原 pane")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
