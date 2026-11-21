#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORAGE = ROOT / "common" / "storage.py"
REGISTRY = ROOT / "common" / "registry.py"
MCP = ROOT / "mcp" / "mailbox_mcp.py"
HUB = ROOT / "hub" / "hub.py"
FED = ROOT / "common" / "federation.py"


def lint() -> list[str]:
    problems = []
    storage_src = STORAGE.read_text()
    if "def id_is_safe" not in storage_src or 'r"^[A-Za-z0-9_-]{1,96}$"' not in storage_src:
        problems.append("common/storage.py: 缺 id_is_safe 字符集白名单——LLM 可控 id 进入路径拼接的唯一闸门")
    for func in ("def write_ack", "def read_msg", "def msg_in_queue", "def ack_exists", "def find_ack_target"):
        body = storage_src.split(func, 1)[-1].split("\ndef ", 1)[0]
        if "id_is_safe" not in body:
            problems.append(f"common/storage.py: {func} 缺 id_is_safe 前置——{func.split()[1]} 的参数可达路径拼接, 2026-11-13 审计: ack_id='../../registry.json' 任意文件写")
    registry_src = REGISTRY.read_text()
    upsert_body = registry_src.split("def upsert", 1)[-1].split("\ndef ", 1)[0]
    batch_body = registry_src.split("def apply_batch", 1)[-1].split("\ndef ", 1)[0]
    if "id_is_safe" not in upsert_body:
        problems.append("common/registry.py: upsert 键缺 id_is_safe——恶意 agent_id 直通 storage 路径拼接")
    if "id_is_safe" not in batch_body:
        problems.append("common/registry.py: apply_batch 键缺 id_is_safe——联邦合并是对端 registry 半可信输入的唯一入口")
    mcp_src = MCP.read_text()
    for func in ("def do_read", "def do_ack"):
        body = mcp_src.split(func, 1)[-1].split("\ndef ", 1)[0]
        if "id_is_safe" not in body:
            problems.append(f"mcp/mailbox_mcp.py: {func} 入口缺 id_is_safe(提示注入即攻击面, 工具参数是 LLM 生成)")
    hub_src = HUB.read_text()
    if "and spawn_cmd and not ssh_host:" not in hub_src:
        problems.append(
            "hub/hub.py: spawn 分支必须 not ssh_host——联邦合并的记录带 spawn_cmd 时, 恶意 peer 一封信即触发本地 Popen 任意命令执行"
        )
    fed_src = FED.read_text()
    if "def sanitize_merged_record" not in fed_src or '"spawn_cmd"' not in fed_src:
        problems.append("common/federation.py: 联邦合并必须剥离执行类字段(spawn_cmd/codex_bin/codex_home/codex_thread/rpc_inbox_url)")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
