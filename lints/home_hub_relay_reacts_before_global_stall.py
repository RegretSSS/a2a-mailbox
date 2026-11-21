#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HUB = (ROOT / "hub" / "hub.py").read_text(encoding="utf-8")


def lint() -> list[str]:
    problems = []
    if "HOME_RELAY_STALL_SECONDS" not in HUB:
        problems.append(
            "hub/hub.py: 缺 HOME_RELAY_STALL_SECONDS——镜像档滞留信若吃全局 OFFLINE_STALL_SECONDS(1800s)"
            "才 relay 回 home hub, 跨机回信延迟半小时(codex 收不到 host-b 回信实案)"
        )
    if "stall_threshold = HOME_RELAY_STALL_SECONDS if home_hub else OFFLINE_STALL_SECONDS" not in HUB:
        problems.append(
            "hub/hub.py: sweep_offline_stalled 未按 home_hub 分档滞留门槛——"
            "relay 提速失效回退成 1800s 全局等待"
        )
    sweep_body = HUB.split("def sweep_offline_stalled")[1].split("\ndef ")[0]
    if "anchors_complete" in sweep_body:
        relay_may_consume = "relay 只消费 ssh_alias"
        problems.append(
            "hub/hub.py: sweep_offline_stalled 的 home_hub 判定不得依赖 anchors_complete——"
            "镜像档 exec 字段在联邦 merge 时被安全剥离(a15a701), anchors 恒 False,"
            " relay 提速分支对镜像档永不触发, 跨机回信干等 1800s(e6f8cf0e 实案); "
            + relay_may_consume + ", 锚完整性与镜像档无关"
        )
    if "and (\n                    codexq.anchors_complete(record)" in HUB:
        problems.append(
            "hub/hub.py: 投递主循环镜像档 relay 分支(ssh_alias 章)不得与 anchors_complete 组合判定——"
            "codex 镜像档 anchors 恒 False 不命中即时 relay, 落队列等 sweep 滞留窗;"
            "pi/claude 镜像档命中 native-inbox 条件即时 relay, 同 hub 两档两速实案;"
            "镜像档统一 ssh_alias 章即 relay, 通道类型不该分流"
        )
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
