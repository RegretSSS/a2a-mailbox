import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from common import federation, registry, storage


def test_write_ack_rejects_traversal(tmp_path):
    with pytest.raises(ValueError):
        storage.write_ack(tmp_path, "../../registry.json", "claude-a")
    assert not (tmp_path.parent.parent / "registry.json").exists()


def test_ack_exists_traversal_is_false(tmp_path):
    assert storage.ack_exists(tmp_path, "../peers.json") is False


def test_registry_upsert_rejects_unsafe_agent_id(tmp_path):
    with pytest.raises(ValueError):
        registry.upsert(tmp_path, "evil/../../agents", {"cli": "claude"})
    assert "evil/../../agents" not in registry.load(tmp_path)["agents"]


def test_registry_apply_batch_filters_unsafe_keys(tmp_path):
    registry.apply_batch(
        tmp_path,
        {
            "good-agent-1": {"cli": "claude"},
            "bad/../escape": {"cli": "claude"},
        },
    )
    agents = registry.load(tmp_path)["agents"]
    assert "good-agent-1" in agents
    assert "bad/../escape" not in agents


def test_read_msg_traversal_returns_none(tmp_path):
    assert storage.read_msg(tmp_path, "claude-a", "../claude-b/m1") is None
    assert storage.read_msg(tmp_path, "../escape", "m1") is None
    assert storage.msg_in_queue(tmp_path, "claude-a", "../x") is False


def test_find_ack_target_traversal_returns_none(tmp_path):
    assert storage.find_ack_target(tmp_path, "../x") is None


@pytest.fixture
def mailbox_mod(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    spec = importlib.util.spec_from_file_location(
        "mailbox_sec_mod", str(Path(__file__).resolve().parent.parent / "mcp" / "mailbox_mcp.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.SELF = {"agent_id": "claude-sec-1"}
    return module


def test_do_ack_rejects_traversal(mailbox_mod, tmp_path):
    registry.upsert(tmp_path, "claude-sec-1", {"cli": "claude", "pane_id": "%1"})
    out = mailbox_mod.do_ack("claude-sec-1", "../../registry.json")
    assert '"ok": false' in out or '"ok":false' in out
    assert "非法字符" in out


def test_do_read_rejects_traversal(mailbox_mod, tmp_path):
    registry.upsert(tmp_path, "claude-sec-1", {"cli": "claude", "pane_id": "%1"})
    out = mailbox_mod.do_read("claude-sec-1", "../other/secret")
    assert "非法字符" in out


def test_federation_merge_strips_spawn_cmd(tmp_path, monkeypatch):
    registry.upsert(tmp_path, "local-1", {"cli": "claude"})
    malicious = {
        "agents": {
            "fed-spawn-target": {
                "agent_id": "fed-spawn-target",
                "cli": "codex",
                "spawn_cmd": ["/tmp/evil"],
                "codex_bin": "/tmp/evil-bin",
                "pane_id": "%9",
            }
        }
    }
    monkeypatch.setattr(
        "common.sshio.read_remote_federation_snapshot",
        lambda alias, probe_ids: ("ok", {"registry": malicious, "queue": [], "settled": {}}),
    )
    result = federation.pull_peer(tmp_path, "host-b")
    assert result["ok"] is True
    merged = registry.load(tmp_path)["agents"]["fed-spawn-target"]
    assert "spawn_cmd" not in merged
    assert "codex_bin" not in merged
    assert merged["pane_id"] == "%9"
