import importlib.util
import json
import time
from pathlib import Path

from common import magpie_bridge

_SPEC = importlib.util.spec_from_file_location(
    "mailbox_mcp", Path(__file__).resolve().parent.parent / "mcp" / "mailbox_mcp.py"
)
mailbox_mcp = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mailbox_mcp)


def make_root(tmp_path, agents, sessions=None):
    root = tmp_path / "mailbox"
    root.mkdir()
    (root / "registry.json").write_text(json.dumps({"agents": agents}))
    if sessions is not None:
        (root / magpie_bridge.BRIDGE_FILENAME).write_text(json.dumps({"sessions": sessions, "agents": {}}))
    return root


AGENTS = {
    "codex-host-a-alpha": {"cli": "codex", "cwd": "/w/alpha"},
    "claude-host-a-beta": {"cli": "claude", "cwd": "/w/beta"},
    "pi-host-a-gamma": {"cli": "pi", "cwd": "/w/gamma"},
}


def test_hosting_matches_cli_and_cwd_with_fresh_ts(tmp_path):
    now = time.time()
    sessions = {
        "codex|s1": {"cwd": "/w/alpha", "ts": (now - 60) * 1000},
        "claude-code|s2": {"cwd": "/w/beta", "ts": (now - 60) * 1000},
    }
    root = make_root(tmp_path, AGENTS, sessions)
    hosting = magpie_bridge.magpie_hosting(root, {"agents": AGENTS}, now=now)
    assert hosting["codex-host-a-alpha"] is True
    assert hosting["claude-host-a-beta"] is True
    assert hosting["pi-host-a-gamma"] is False


def test_stale_heartbeat_beyond_ttl_is_not_hosting(tmp_path):
    now = time.time()
    sessions = {"codex|s1": {"cwd": "/w/alpha", "ts": (now - magpie_bridge.HOSTING_TTL_SECONDS - 30) * 1000}}
    root = make_root(tmp_path, AGENTS, sessions)
    hosting = magpie_bridge.magpie_hosting(root, {"agents": AGENTS}, now=now)
    assert hosting["codex-host-a-alpha"] is False


def test_cwd_mismatch_is_not_hosting(tmp_path):
    now = time.time()
    sessions = {"codex|s1": {"cwd": "/w/elsewhere", "ts": (now - 60) * 1000}}
    root = make_root(tmp_path, AGENTS, sessions)
    hosting = magpie_bridge.magpie_hosting(root, {"agents": AGENTS}, now=now)
    assert hosting["codex-host-a-alpha"] is False


def test_cli_mismatch_is_not_hosting(tmp_path):
    now = time.time()
    sessions = {"pi|s1": {"cwd": "/w/alpha", "ts": (now - 60) * 1000}}
    root = make_root(tmp_path, AGENTS, sessions)
    hosting = magpie_bridge.magpie_hosting(root, {"agents": AGENTS}, now=now)
    assert hosting["codex-host-a-alpha"] is False


def test_missing_bridge_file_marks_nothing(tmp_path):
    root = make_root(tmp_path, AGENTS)
    hosting = magpie_bridge.magpie_hosting(root, {"agents": AGENTS})
    assert not any(hosting.values())


def test_corrupt_bridge_file_is_tolerated(tmp_path):
    root = tmp_path / "mailbox"
    root.mkdir()
    (root / "registry.json").write_text(json.dumps({"agents": AGENTS}))
    (root / magpie_bridge.BRIDGE_FILENAME).write_text("{not json")
    hosting = magpie_bridge.magpie_hosting(root, {"agents": AGENTS})
    assert not any(hosting.values())


def test_who_roster_carries_magpie_flag(tmp_path, monkeypatch):
    root = make_root(tmp_path, AGENTS, {"codex|s1": {"cwd": "/w/alpha", "ts": time.time() * 1000}})
    monkeypatch.setattr(mailbox_mcp.paths, "mailbox_root", lambda: root)
    monkeypatch.setattr(mailbox_mcp.federation, "pull_all", lambda *a, **k: [])
    monkeypatch.setattr(mailbox_mcp.storage, "load_online", lambda *a, **k: {})
    monkeypatch.setattr(mailbox_mcp.registry, "touch", lambda *a, **k: None)
    payload = json.loads(mailbox_mcp.do_who("codex-host-a-alpha"))
    by_id = {entry["agent_id"]: entry for entry in payload["agents"]}
    assert by_id["codex-host-a-alpha"]["magpie"] is True
    assert "magpie" not in by_id["claude-host-a-beta"]
