import json
import time
import uuid
from pathlib import Path

from common import atomicio, lockfile, paths

RATE_WINDOW_SECONDS = 60.0
RATE_MAX_PER_WINDOW = 10


def new_ids() -> tuple[str, str]:
    msg_id = uuid.uuid4().hex[:12]
    return msg_id, f"ack-{msg_id}"


def queue_dir(root: Path, agent_id: str) -> Path:
    return root / paths.QUEUE_DIR / agent_id


def msg_path(root: Path, agent_id: str, msg_id: str) -> Path:
    return queue_dir(root, agent_id) / f"{msg_id}.msg"


def read_json(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def enqueue(root: Path, envelope: dict) -> Path:
    path = msg_path(root, envelope["to"], envelope["msg_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    atomicio.write_json_atomic(path, envelope)
    return path


def stamp_injected(root: Path, agent_id: str, msg_id: str, now: float) -> None:
    path = msg_path(root, agent_id, msg_id)
    envelope = read_json(path)
    if envelope is None:
        return
    envelope["last_injected_at"] = now
    atomicio.write_json_atomic(path, envelope)


def stamp_stall_notified(root: Path, agent_id: str, msg_id: str, now: float) -> None:
    path = msg_path(root, agent_id, msg_id)
    envelope = read_json(path)
    if envelope is None:
        return
    envelope["stall_notified_at"] = now
    atomicio.write_json_atomic(path, envelope)


def to_epoch(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def stamp_queue_attempt(root: Path, agent_id: str, msg_id: str, now: float, delay_seconds: float, attempts: int) -> None:
    path = msg_path(root, agent_id, msg_id)
    envelope = read_json(path)
    if envelope is None:
        return
    envelope["queue_attempts"] = attempts
    envelope["queue_retry_not_before"] = now + delay_seconds
    envelope["last_injected_at"] = 0
    atomicio.write_json_atomic(path, envelope)


def queue_retry_pending(envelope: dict, now: float) -> bool:
    return to_epoch(envelope.get("queue_retry_not_before")) > now


def stamp_home_relay(root: Path, agent_id: str, msg_id: str, now: float) -> None:
    path = msg_path(root, agent_id, msg_id)
    envelope = read_json(path)
    if envelope is None:
        return
    if not envelope.get("home_relay_first_at"):
        envelope["home_relay_first_at"] = now
    envelope["home_relay_last_try"] = now
    atomicio.write_json_atomic(path, envelope)


def recently_injected(envelope: dict, now: float, guard_seconds: float) -> bool:
    stamp = to_epoch(envelope.get("last_injected_at"))
    return 0 < stamp and now - stamp < guard_seconds


def created_at_of(envelope: dict) -> float:
    return to_epoch(envelope.get("created_at"))


def list_queue(root: Path, agent_id: str) -> list[dict]:
    envelopes = []
    for path in queue_dir(root, agent_id).glob("*.msg"):
        envelope = read_json(path)
        if envelope is not None:
            envelopes.append(envelope)
    envelopes.sort(key=created_at_of)
    return envelopes


def read_msg(root: Path, agent_id: str, msg_id: str) -> dict | None:
    return read_json(msg_path(root, agent_id, msg_id))


def msg_in_queue(root: Path, agent_id: str, msg_id: str) -> bool:
    return msg_path(root, agent_id, msg_id).is_file()


def find_msg(root: Path, msg_id: str) -> dict | None:
    queue_root = root / paths.QUEUE_DIR
    if queue_root.is_dir():
        for agent_dir in sorted(queue_root.iterdir()):
            envelope = read_json(agent_dir / f"{msg_id}.msg")
            if envelope is not None:
                return envelope
    return read_json(root / paths.HISTORY_DIR / f"{msg_id}.json")


def history_path(root: Path, msg_id: str) -> Path:
    return root / paths.HISTORY_DIR / f"{msg_id}.json"


def archive_msg(root: Path, agent_id: str, msg_id: str) -> None:
    src = msg_path(root, agent_id, msg_id)
    if not src.exists():
        return
    dst = history_path(root, msg_id)
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.replace(dst)


def write_online(root: Path, online: dict, now: float) -> None:
    payload = {"agents": {agent_id: bool(alive) for agent_id, alive in online.items()}, "ts": now}
    atomicio.write_json_atomic(root / paths.ONLINE_FILE, payload)


def load_online(root: Path) -> dict:
    payload = read_json(root / paths.ONLINE_FILE)
    if not isinstance(payload, dict):
        return {}
    agents = payload.get("agents")
    return agents if isinstance(agents, dict) else {}


def discard_msg(root: Path, agent_id: str, msg_id: str) -> None:
    msg_path(root, agent_id, msg_id).unlink(missing_ok=True)


def mark_failed(root: Path, agent_id: str, msg_id: str) -> Path:
    src = msg_path(root, agent_id, msg_id)
    dst = src.with_suffix(".failed")
    try:
        src.replace(dst)
    except FileNotFoundError:
        pass
    return dst


def ack_path(root: Path, ack_id: str) -> Path:
    return root / paths.ACKS_DIR / ack_id


def write_ack(root: Path, ack_id: str, by: str) -> None:
    path = ack_path(root, ack_id)
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    atomicio.write_json_atomic(path, {"ack_id": ack_id, "by": by, "ts": time.time()})


def ack_exists(root: Path, ack_id: str) -> bool:
    return ack_path(root, ack_id).exists()


def find_ack_target(root: Path, ack_id: str) -> dict | None:
    queue_root = root / paths.QUEUE_DIR
    if not queue_root.is_dir():
        return None
    for agent_dir in sorted(queue_root.iterdir()):
        for path in agent_dir.glob("*.msg"):
            envelope = read_json(path)
            if envelope is not None and envelope.get("ack_id") == ack_id:
                return envelope
    return None


def pair_key(from_id: str, to_id: str) -> str:
    return "__".join(sorted([from_id, to_id]))


def rate_gate(root: Path, from_id: str, to_id: str, now: float | None = None) -> tuple[bool, float]:
    moment = time.time() if now is None else float(now)
    ledger_dir = root / paths.RATES_DIR
    ledger_dir.mkdir(parents=True, exist_ok=True)
    ledger = ledger_dir / f"{pair_key(from_id, to_id)}.ledger"
    with ledger.open("a+") as handle:
        lockfile.lock_exclusive_blocking(handle)
        handle.seek(0)
        recent = []
        for line in handle.read().splitlines():
            try:
                stamp = float(line)
            except ValueError:
                continue
            if moment - stamp < RATE_WINDOW_SECONDS:
                recent.append(stamp)
        allowed = len(recent) < RATE_MAX_PER_WINDOW
        retry_after = 0.0
        if not allowed and recent:
            retry_after = max(0.0, RATE_WINDOW_SECONDS - (moment - min(recent)))
        kept = [*recent, moment] if allowed else recent
        handle.seek(0)
        handle.truncate()
        for stamp in kept:
            handle.write(f"{stamp}\n")
        handle.flush()
        lockfile.unlock(handle)
    return allowed, retry_after
