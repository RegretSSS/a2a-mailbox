import json
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import registry


def test_load_empty_root_returns_empty_agents(tmp_path):
    assert registry.load(tmp_path)["agents"] == {}


def test_upsert_then_get(tmp_path):
    registry.upsert(tmp_path, "claude-h-1", {"cli": "claude", "pane_id": "%1"})
    record = registry.get(tmp_path, "claude-h-1")
    assert record["cli"] == "claude"
    assert record["pane_id"] == "%1"
    assert record["agent_id"] == "claude-h-1"
    assert record["last_seen"] > 0


def test_upsert_preserves_other_agents(tmp_path):
    registry.upsert(tmp_path, "claude-h-1", {"cli": "claude"})
    registry.upsert(tmp_path, "codex-h-2", {"cli": "codex"})
    agents = registry.load(tmp_path)["agents"]
    assert set(agents) == {"claude-h-1", "codex-h-2"}


def test_upsert_overwrites_stale_pane_pid(tmp_path):
    registry.upsert(tmp_path, "claude-h-1", {"pane_pid": "100"})
    registry.upsert(tmp_path, "claude-h-1", {"pane_pid": "200", "started_at": 1.5})
    record = registry.get(tmp_path, "claude-h-1")
    assert record["pane_pid"] == "200"
    assert record["started_at"] == 1.5


def test_touch_refreshes_last_seen(tmp_path):
    registry.upsert(tmp_path, "claude-h-1", {"cli": "claude", "last_seen": 1.0})
    before = registry.get(tmp_path, "claude-h-1")["last_seen"]
    registry.touch(tmp_path, "claude-h-1")
    after = registry.get(tmp_path, "claude-h-1")["last_seen"]
    assert after >= before
    assert after > 1.0


def test_touch_on_unknown_agent_creates_no_stub(tmp_path):
    registry.touch(tmp_path, "claude-ghost-1")
    assert registry.get(tmp_path, "claude-ghost-1") is None
    assert registry.load(tmp_path)["agents"] == {}


def test_corrupt_registry_resets_to_empty(tmp_path):
    (tmp_path / "registry.json").write_text("{not json")
    assert registry.load(tmp_path)["agents"] == {}


def test_concurrent_upserts_both_land(tmp_path):
    def hammer(agent_id):
        for index in range(30):
            registry.upsert(tmp_path, agent_id, {"index": index})

    threads = [
        threading.Thread(target=hammer, args=("claude-h-1",)),
        threading.Thread(target=hammer, args=("codex-h-2",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    agents = registry.load(tmp_path)["agents"]
    assert set(agents) == {"claude-h-1", "codex-h-2"}


def test_registry_stamps_schema_version(tmp_path):
    from common import registry as reg

    reg.upsert(tmp_path, "a-1", {"cli": "claude"})
    payload = json.loads((tmp_path / "registry.json").read_text())
    assert payload["schema_version"] == 1


def test_registry_load_tolerates_missing_schema_version(tmp_path):
    from common import registry as reg

    (tmp_path / "registry.json").write_text('{"agents": {"old-1": {"cli": "claude"}}}')
    assert reg.load(tmp_path)["agents"]["old-1"]["cli"] == "claude"
    assert "schema_version" not in reg.load(tmp_path)
    reg.upsert(tmp_path, "a-2", {"cli": "pi"})
    assert reg.load(tmp_path)["schema_version"] == 1
