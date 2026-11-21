#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import detect, paths, registry, storage


def migrated_agents(agents: dict, qualifier: str) -> tuple[dict, list]:
    local = {
        agent_id: record
        for agent_id, record in agents.items()
        if not str(record.get("ssh_alias") or "")
    }
    renamed: dict = {}
    mapping = []
    for agent_id, record in sorted(local.items(), key=lambda item: item[1].get("started_at") or 0):
        new_id = (
            f"{record.get('cli', 'unknown')}-{qualifier}-"
            f"{detect.workspace_slug(str(record.get('cwd') or 'root'))}"
        )
        fresh = dict(record)
        fresh["agent_id"] = new_id
        renamed[new_id] = fresh
        if new_id != agent_id:
            mapping.append({"from": agent_id, "to": new_id})
    return renamed, mapping


def move_queues(root: Path, mapping: list) -> None:
    for item in mapping:
        old_dir = storage.queue_dir(root, item["from"])
        new_dir = storage.queue_dir(root, item["to"])
        if old_dir.exists() and any(old_dir.iterdir()):
            new_dir.mkdir(parents=True, exist_ok=True)
            for entry in old_dir.iterdir():
                entry.rename(new_dir / entry.name)
        if old_dir.exists():
            old_dir.rmdir()


def main() -> None:
    parser = argparse.ArgumentParser(description="agent_id host 段迁移为 tailscale/ssh_alias 身份（联邦记录丢弃待重拉）")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    qualifier = detect.host_qualifier()
    root = paths.mailbox_root()
    agents = registry.load(root)["agents"]
    renamed, mapping = migrated_agents(agents, qualifier)
    dropped = [
        agent_id
        for agent_id, record in agents.items()
        if str(record.get("ssh_alias") or "")
    ]
    if args.dry_run:
        print(json.dumps({"qualifier": qualifier, "mapping": mapping, "dropped": dropped}, ensure_ascii=False))
        return

    def replace(agents_dict):
        agents_dict.clear()
        agents_dict.update(renamed)

    registry.locked_agents_mutate(root, replace)
    move_queues(root, mapping)
    print(json.dumps({"qualifier": qualifier, "mapping": mapping, "dropped": dropped}, ensure_ascii=False))


if __name__ == "__main__":
    main()
