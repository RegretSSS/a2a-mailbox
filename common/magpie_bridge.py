import json
import time
from pathlib import Path

BRIDGE_FILENAME = "magpie-bridge.json"
HOSTING_TTL_SECONDS = 600

MAGPIE_AGENT_TO_CLI = (
    ("claude", "claude"),
    ("codex", "codex"),
    ("pi", "pi"),
)


def _cli_for_magpie_agent(agent: str) -> str:
    if agent.startswith("claude"):
        return "claude"
    for needle, cli in MAGPIE_AGENT_TO_CLI:
        if agent == needle:
            return cli
    return ""


def load_bridge(root: Path) -> dict:
    try:
        state = json.loads((root / BRIDGE_FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(state, dict):
        return {}
    sessions = state.get("sessions")
    return state if isinstance(sessions, dict) else {}


def magpie_hosting(root: Path, reg: dict, now: float | None = None) -> dict:
    state = load_bridge(root)
    sessions = state.get("sessions") or {}
    moment = time.time() if now is None else now
    by_cli_cwd: dict[tuple, float] = {}
    for session_key, record in sessions.items():
        if not isinstance(record, dict):
            continue
        agent = str(session_key).split("|", 1)[0]
        ts = float(record.get("ts") or 0)
        if ts <= 0 or moment - ts / 1000 > HOSTING_TTL_SECONDS:
            continue
        cwd = str(record.get("cwd") or "")
        cli = _cli_for_magpie_agent(agent)
        if not cli or not cwd:
            continue
        key = (cli, cwd)
        if ts > by_cli_cwd.get(key, 0):
            by_cli_cwd[key] = ts
    hosting: dict = {}
    for agent_id, record in (reg.get("agents") or {}).items():
        cli = str(record.get("cli") or "")
        cwd = str(record.get("cwd") or "")
        hosting[agent_id] = bool(cli and cwd and (cli, cwd) in by_cli_cwd)
    return hosting
