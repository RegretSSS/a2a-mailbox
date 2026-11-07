import json
import time
from pathlib import Path

ALIVE_FILENAME = "alive.json"
ALIVE_HEARTBEAT_SECONDS = 20.0
ALIVE_TTL_SECONDS = 60.0
NATIVE_DIR = "native-inbox"


def agent_dir(root: Path, agent_id: str) -> Path:
    return root / NATIVE_DIR / agent_id


def alive_path(root: Path, agent_id: str) -> Path:
    return agent_dir(root, agent_id) / ALIVE_FILENAME


def rcpt_path(root: Path, agent_id: str, msg_id: str) -> Path:
    return agent_dir(root, agent_id) / f"rcpt-{msg_id}"


def write_alive(root: Path, agent_id: str, pid: int, now: float | None = None) -> None:
    moment = time.time() if now is None else now
    target = alive_path(root, agent_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"{ALIVE_FILENAME}.tmp")
    tmp.write_text(json.dumps({"pid": pid, "ts": moment}, ensure_ascii=False))
    tmp.replace(target)


def alive_fresh(root: Path, agent_id: str, now: float | None = None) -> bool:
    target = alive_path(root, agent_id)
    try:
        payload = json.loads(target.read_text())
    except (OSError, ValueError):
        return False
    ts = float(payload.get("ts") or 0)
    moment = time.time() if now is None else now
    return ts > 0 and moment - ts < ALIVE_TTL_SECONDS


def write_rcpt(root: Path, agent_id: str, msg_id: str, now: float | None = None) -> bool:
    moment = time.time() if now is None else now
    target = rcpt_path(root, agent_id, msg_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = open(target, "x")
    except FileExistsError:
        return False
    with handle:
        handle.write(json.dumps({"ts": moment}, ensure_ascii=False))
    return True


def rcpt_exists(root: Path, agent_id: str, msg_id: str) -> bool:
    if rcpt_path(root, agent_id, msg_id).is_file():
        return True
    inbox = root / NATIVE_DIR
    return inbox.is_dir() and bool(list(inbox.glob(f"*/rcpt-{msg_id}")))
