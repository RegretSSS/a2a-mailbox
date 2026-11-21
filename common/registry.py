import json
import time
from pathlib import Path

from common import atomicio, lockfile, paths, storage
from common.version import SCHEMA_VERSION

TOUCH_THROTTLE_SECONDS = 60.0
_touch_last_seen_at: dict[str, float] = {}

TOMBSTONE_DIRNAME = "tombstones"
TOMBSTONE_TTL_SECONDS = 7 * 86400.0


def tombstone_path(root: Path, agent_id: str) -> Path:
    return root / TOMBSTONE_DIRNAME / f"{agent_id}.json"


def write_tombstone(root: Path, agent_id: str) -> None:
    if not storage.id_is_safe(agent_id):
        return
    path = tombstone_path(root, agent_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomicio.write_json_atomic(path, {"agent_id": agent_id, "forgotten_at": time.time()})


def tombstone_at(root: Path, agent_id: str) -> float:
    try:
        payload = json.loads(tombstone_path(root, agent_id).read_text())
    except (OSError, ValueError):
        return 0.0
    stamp = payload.get("forgotten_at") if isinstance(payload, dict) else None
    return float(stamp) if isinstance(stamp, (int, float)) else 0.0


def clear_tombstone(root: Path, agent_id: str) -> None:
    try:
        tombstone_path(root, agent_id).unlink()
    except OSError:
        pass


def prune_tombstones(root: Path) -> int:
    now = time.time()
    pruned = 0
    directory = root / TOMBSTONE_DIRNAME
    try:
        entries = list(directory.iterdir())
    except OSError:
        return 0
    for path in entries:
        if not path.name.endswith(".json"):
            continue
        try:
            payload = json.loads(path.read_text())
            forgotten_at = float(payload.get("forgotten_at") or 0.0)
        except (OSError, ValueError, TypeError):
            forgotten_at = 0.0
        if now - forgotten_at > TOMBSTONE_TTL_SECONDS:
            try:
                path.unlink()
                pruned += 1
            except OSError:
                continue
    return pruned


def registry_file(root: Path) -> Path:
    return root / paths.REGISTRY_FILE


class RegistryUnavailable(Exception):
    pass


def try_load(root: Path, on_corrupt=None) -> dict:
    try:
        text = registry_file(root).read_text()
    except FileNotFoundError:
        return {"agents": {}, "schema_version": SCHEMA_VERSION}
    except OSError as exc:
        raise RegistryUnavailable(f"{registry_file(root)}: {exc}")
    try:
        payload = json.loads(text)
    except ValueError as exc:
        if on_corrupt is not None:
            on_corrupt(exc)
        return {"agents": {}, "schema_version": SCHEMA_VERSION}
    if not isinstance(payload.get("agents"), dict):
        return {"agents": {}, "schema_version": SCHEMA_VERSION}
    return payload


def load(root: Path, on_corrupt=None) -> dict:
    try:
        return try_load(root, on_corrupt)
    except RegistryUnavailable:
        return {"agents": {}, "schema_version": SCHEMA_VERSION}


_PAYLOAD_CACHE: dict = {}


def load_cached(root: Path) -> dict:
    path = registry_file(root)
    cache_key = str(path)
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return {"agents": {}, "schema_version": SCHEMA_VERSION}
    cached = _PAYLOAD_CACHE.get(cache_key)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    payload = load(root)
    _PAYLOAD_CACHE[cache_key] = (mtime, payload)
    return payload


def get(root: Path, agent_id: str) -> dict | None:
    return load_cached(root)["agents"].get(agent_id)


def locked_agents_mutate(root: Path, mutate) -> bool:
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / paths.REGISTRY_LOCK
    with lock_path.open("a+") as lock:
        lockfile.lock_exclusive_blocking(lock)
        payload = load(root)
        payload.setdefault("schema_version", SCHEMA_VERSION)
        if mutate(payload["agents"]) is False:
            lockfile.unlock(lock)
            return False
        atomicio.write_json_atomic(registry_file(root), payload)
        lockfile.unlock(lock)
        return True


def upsert(root: Path, agent_id: str, fields: dict) -> dict:
    if not storage.id_is_safe(agent_id):
        raise ValueError(f"agent_id 非法字符集, 拒绝入册: {agent_id!r}")
    record = dict(fields)
    record["agent_id"] = agent_id
    record["last_seen"] = time.time()

    def merge(agents):
        agents[agent_id] = record
        return True

    locked_agents_mutate(root, merge)
    return record


def apply_batch(root: Path, records: dict) -> None:
    if not records:
        return
    for agent_id in list(records):
        if not storage.id_is_safe(agent_id):
            del records[agent_id]
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
        return True

    locked_agents_mutate(root, merge)


def touch(root: Path, agent_id: str) -> bool:
    now = time.time()
    if now - _touch_last_seen_at.get(agent_id, 0.0) < TOUCH_THROTTLE_SECONDS:
        return False

    def stamp(agents):
        existing = agents.get(agent_id)
        if existing is None:
            return False
        _touch_last_seen_at[agent_id] = now
        existing["last_seen"] = now
        agents[agent_id] = existing
        return True

    stamped = locked_agents_mutate(root, stamp)
    if stamped:
        clear_tombstone(root, agent_id)
    return stamped


def forget(root: Path, agent_id: str) -> None:
    def drop(agents):
        return agents.pop(agent_id, None) is not None

    removed = locked_agents_mutate(root, drop)
    if removed:
        _touch_last_seen_at.pop(agent_id, None)
        write_tombstone(root, agent_id)
