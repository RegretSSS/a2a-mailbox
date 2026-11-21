#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "common" / "registry.py"
HUB = ROOT / "hub" / "hub.py"
NOTIFIER = ROOT / "common" / "queuenotify.py"
SSHIO = ROOT / "common" / "sshio.py"


def lint() -> list[str]:
    problems = []
    registry_src = REGISTRY.read_text()
    if "class RegistryUnavailable" not in registry_src:
        problems.append("common/registry.py: 必须有 RegistryUnavailable——瞬态读失败与真坏文件不分家则 hub 拿空表判全孤儿")
    load_body = registry_src.split("def try_load", 1)[-1].split("def ", 1)[0]
    if "except FileNotFoundError" not in load_body or "RegistryUnavailable" not in load_body:
        problems.append(
            "common/registry.py: try_load 必须区分 FileNotFoundError(空表正常)与其余 OSError(RegistryUnavailable)——"
            "一刀切 OSError 会把全新环境当瞬态, 一刀切空表会把 EMFILE 当无 agent"
        )
    if "def load" not in registry_src or "except RegistryUnavailable" not in registry_src.split("def load", 1)[-1].split("def ", 1)[0]:
        problems.append("common/registry.py: load 兼容包装必须捕 RegistryUnavailable 回空表(只读调用方不崩)")

    hub_src = HUB.read_text()
    main_loop = hub_src.split("def main", 1)[-1]
    if "registry.try_load" not in main_loop:
        problems.append("hub/hub.py: 主循环必须用 registry.try_load——load 会把瞬态失败吞成空表, 直接喂孤儿化")
    if "RegistryUnavailable" not in main_loop:
        problems.append("hub/hub.py: 主循环必须处理 RegistryUnavailable 跳过本轮(不孤儿化/不剪枝/不判活)")
    if "registry.try_load" not in hub_src.split("def sweep_orphan_queues", 1)[-1].split("def ", 1)[0]:
        problems.append("hub/hub.py: sweep_orphan_queues 必须 fresh 重查 try_load——入参 reg 可能是失败读的旧空表")
    if "return []" not in hub_src.split("def sweep_orphan_queues", 1)[-1].split("def ", 1)[0]:
        problems.append("hub/hub.py: sweep_orphan_queues 瞬态读失败必须 return [] 放弃本轮扫描")

    notifier_src = NOTIFIER.read_text()
    watch_tree = notifier_src.split("def _watch_tree", 1)[-1].split("def ", 1)[0]
    if "except FileNotFoundError" not in watch_tree or "return" not in watch_tree:
        problems.append(
            "common/queuenotify.py: _watch_tree 对已删目录必须捕 FileNotFoundError 降级 return——"
            "iterdir 抛异常会打断每轮 tick, 投递永久停摆"
        )

    sshio_src = SSHIO.read_text()
    if "REMOTE_ACK_UNREACHABLE" not in sshio_src:
        problems.append("common/sshio.py: remote ack 探测必须三态(PRESENT/ABSENT/UNREACHABLE)——二态把不可达当未 ack")
    ack_body = sshio_src.split("def remote_ack_state", 1)[-1].split("def ", 1)[0]
    if "255" not in ack_body or "REMOTE_ACK_UNREACHABLE" not in ack_body:
        problems.append("common/sshio.py: remote_ack_state 对 ssh rc=255 必须判 UNREACHABLE 而非 ABSENT")
    delivery = hub_src.split("class Delivery", 1)[-1].split("def build_delivery", 1)[0]
    if delivery.count("ack_probe_lost_at") < 4:
        problems.append(
            f"hub/hub.py: Delivery 对 ack_probe_lost_at 至少 4 处消费(置位/清除/inject 挂起/WAIT_CONFIRM 冻结/WAIT_ACK 冻结), 实际 {delivery.count('ack_probe_lost_at')}——"
            "缺一处则远端断链期间 120s ACK_TIMEOUT 假超时回弹已 ack 信"
        )
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
