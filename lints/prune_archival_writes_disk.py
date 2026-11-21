#!/usr/bin/env python3
import importlib.util
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCAL_DEAD = "claude-host-a-a2a-mailbox"
REMOTE_STALE = "codex-node-9-remote-workspace"


class SilentLog:
    def __init__(self):
        self.lines = []

    def write(self, line):
        self.lines.append(line)


def prepare():
    workspace = tempfile.mkdtemp(prefix="a2a-lint-")
    os.environ["A2A_MAILBOX_ROOT"] = workspace
    sys.path.insert(0, str(ROOT))
    from common import registry

    spec = importlib.util.spec_from_file_location("hub", ROOT / "hub" / "hub.py")
    hub = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hub)
    root = Path(workspace)
    registry.upsert(
        root,
        LOCAL_DEAD,
        {"cli": "claude", "pane_id": "%9", "pane_pid": "1", "slot": "main:claude"},
    )
    registry.upsert(
        root,
        REMOTE_STALE,
        {"cli": "codex", "pane_id": "%3", "pane_pid": "2", "ssh_alias": "host-b"},
    )
    stale_ts = time.time() - hub.REGISTRY_PRUNE_TTL - 1

    def stale(agents):
        record = agents[REMOTE_STALE]
        record["last_seen"] = stale_ts
        agents[REMOTE_STALE] = record

    registry.locked_agents_mutate(root, stale)
    return hub, registry, root


def lint() -> list[str]:
    problems = []
    hub, registry, root = prepare()
    online = {LOCAL_DEAD: False, REMOTE_STALE: False}
    log = SilentLog()
    pruned = hub.prune_registry({"agents": registry.load(root)["agents"]}, root, log, online, time.time())
    if pruned != []:
        problems.append(f"prune 磁盘写回: 远端档超本机 TTL 即注销 {pruned}——联邦镜像档须走 {hub.REGISTRY_PRUNE_REMOTE_TTL:g}s 宽限, 误杀即跨机信搁浅")

    def age_remote_past_remote_ttl(agents):
        record = agents[REMOTE_STALE]
        record["last_seen"] = time.time() - hub.REGISTRY_PRUNE_REMOTE_TTL - 1
        agents[REMOTE_STALE] = record

    registry.locked_agents_mutate(root, age_remote_past_remote_ttl)
    pruned = hub.prune_registry({"agents": registry.load(root)["agents"]}, root, log, online, time.time())
    if pruned != [REMOTE_STALE]:
        problems.append(f"prune 磁盘写回: 注销判定异常 {pruned}——respawn 处方档(claude)下线应留复活窗, 远端陈旧档过宽限期应注销")
    disk_agents = registry.load(root)["agents"]
    if LOCAL_DEAD not in disk_agents:
        problems.append("prune 磁盘写回: 可复活档在 last_seen 新鲜期内被注销——H8 复活窗失效")
    archive = root / "history" / "registry-pruned.jsonl"
    if not archive.exists() or REMOTE_STALE not in archive.read_text():
        problems.append("prune 磁盘写回: history/registry-pruned.jsonl 未落档或漏远端档")

    stale_ts = time.time() - hub.REGISTRY_PRUNE_TTL - 1

    def age_local(agents):
        record = agents[LOCAL_DEAD]
        record["last_seen"] = stale_ts
        agents[LOCAL_DEAD] = record

    registry.locked_agents_mutate(root, age_local)
    pruned = hub.prune_registry({"agents": registry.load(root)["agents"]}, root, log, online, time.time())
    if pruned != [LOCAL_DEAD]:
        problems.append(f"prune 磁盘写回: 复活窗过期后未注销 {pruned}——陈旧档会无限堆积")
    disk_agents = registry.load(root)["agents"]
    if LOCAL_DEAD in disk_agents:
        problems.append(f"prune 磁盘写回: {LOCAL_DEAD} 注销后仍留在 registry.json——只改内存会造成 hub 每轮 reload 反复注销死循环")
    archived = [json.loads(line) for line in (root / "history" / "registry-pruned.jsonl").read_text().splitlines()]
    if sorted(item.get("agent_id") for item in archived) != sorted([LOCAL_DEAD, REMOTE_STALE]):
        problems.append(f"prune 磁盘写回: 归档内容缺失 {[item.get('agent_id') for item in archived]}")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
