#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def body_of(source: str, name: str) -> str:
    matched = re.search(rf"def {name}\(.*?\n(.*?)(?=\ndef |\nclass |\Z)", source, re.S)
    return matched.group(1) if matched else ""


def lint() -> list[str]:
    problems = []
    hub_source = (ROOT / "hub" / "hub.py").read_text()
    main_body = body_of(hub_source, "main")
    if "acquire_hub_lock" not in main_body:
        problems.append("hub/hub.py: main 必须终生持有 hub.lock(LOCK_NB)——双拉竞态会双注入")
    if "acquire_hub_lock(root)" not in main_body or "lock_handle is None" not in main_body:
        problems.append("hub/hub.py: 抢不到锁必须退出——双 hub 并跑比无 hub 更糟")
    slow_zone = main_body.split("sweep_liveness", 1)[-1]
    if "respawn_offline_spawners" not in slow_zone:
        problems.append("hub/hub.py: 慢路径 sweep 后必须跑 respawn_offline_spawners——否则 offline+spawn_cmd 的在途邮件被 prune 注销吞掉")
    mcp_source = (ROOT / "mcp" / "mailbox_mcp.py").read_text()
    register_body = body_of(mcp_source, "self_register")
    if "boot_hub_if_absent" not in register_body:
        problems.append("mcp/mailbox_mcp.py: self_register 末尾必须 boot_hub_if_absent——首端自举是 hub 缺位时的唯一拉起点")
    boot_body = body_of(mcp_source, "boot_hub_if_absent")
    if "lock_exclusive(handle)" not in boot_body or "start_new_session" not in boot_body or "DETACHED_PROCESS" not in boot_body:
        problems.append(
            "mcp/mailbox_mcp.py: 自举必须 lockfile 非阻塞试锁+进程分离(POSIX start_new_session/纯 win DETACHED_PROCESS)——阻塞或前台拉起会挂死 MCP 注册"
        )
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
