import json
import time
from pathlib import Path

from common import atomicio, lockfile, paths
from common.version import SCHEMA_VERSION


def registry_file(root: Path) -> Path:
    return root / paths.REGISTRY_FILE


def load(root: Path, on_corrupt=None) -> dict:
    try:
        payload = json.loads(registry_file(root).read_text())
    except (OSError, ValueError) as exc:
        if on_corrupt is not None and isinstance(exc, ValueError):
            on_corrupt(exc)
        return {"agents": {}, "schema_version": SCHEMA_VERSION}
    if not isinstance(payload.get("agents"), dict):
        return {"agents": {}, "schema_version": SCHEMA_VERSION}
    return payload


def get(root: Path, agent_id: str) -> dict | None:
    return load(root)["agents"].get(agent_id)


def locked_agents_mutate(root: Path, mutate) -> None:
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / paths.REGISTRY_LOCK
    with lock_path.open("a+") as lock:
        lockfile.lock_exclusive_blocking(lock)
        payload = load(root)
        payload.setdefault("schema_version", SCHEMA_VERSION)
        mutate(payload["agents"])
        atomicio.write_json_atomic(registry_file(root), payload)
        lockfile.unlock(lock)


def upsert(root: Path, agent_id: str, fields: dict) -> dict:
    record = dict(fields)
    record["agent_id"] = agent_id
    record["last_seen"] = time.time()

    def merge(agents):
        agents[agent_id] = record

    locked_agents_mutate(root, merge)
    return record


def apply_batch(root: Path, records: dict) -> None:
    if not records:
        return
    stamped = time.time()
    for agent_id, fields in records.items():
        record = dict(fields)
        record["agent_id"] = agent_id
        record["last_seen"] = stamped
        records[agent_id] = record

    def merge(agents):
        agents.update(records)

    locked_agents_mutate(root, merge)


def touch(root: Path, agent_id: str) -> None:
    def stamp(agents):
        existing = agents.get(agent_id)
        if existing is None:
            return
        existing["last_seen"] = time.time()
        agents[agent_id] = existing

    locked_agents_mutate(root, stamp)


def forget(root: Path, agent_id: str) -> None:
    def drop(agents):
        agents.pop(agent_id, None)

    locked_agents_mutate(root, drop)
