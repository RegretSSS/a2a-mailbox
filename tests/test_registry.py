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


def test_try_load_missing_file_is_empty_registry(tmp_path):
    from common import registry as reg

    assert reg.try_load(tmp_path)["agents"] == {}


def test_try_load_transient_oserror_raises_unavailable(tmp_path, monkeypatch):
    from common import registry as reg

    (tmp_path / "registry.json").write_text('{"agents": {"a-1": {}}}')
    real_read = Path.read_text

    def flaky_read(self, *args, **kwargs):
        if self.name == "registry.json":
            raise OSError(24, "Too many open files")
        return real_read(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", flaky_read)
    try:
        reg.try_load(tmp_path)
        raised = False
    except reg.RegistryUnavailable:
        raised = True
    assert raised
    assert reg.load(tmp_path)["agents"] == {}


def test_try_load_corrupt_json_falls_back_to_empty(tmp_path):
    from common import registry as reg

    (tmp_path / "registry.json").write_text("{broken")
    seen = []
    assert reg.try_load(tmp_path, on_corrupt=seen.append)["agents"] == {}
    assert len(seen) == 1


def test_touch_throttles_rewrites_within_window(tmp_path, monkeypatch):
    from common import registry as reg

    writes = []
    real_write = reg.atomicio.write_json_atomic

    def counting_write(path, payload):
        writes.append(path.name)
        return real_write(path, payload)

    monkeypatch.setattr(reg.atomicio, "write_json_atomic", counting_write)
    monkeypatch.setattr(reg, "_touch_last_seen_at", {})
    reg.upsert(tmp_path, "a-1", {"cli": "claude"})
    writes.clear()

    reg.touch(tmp_path, "a-1")
    reg.touch(tmp_path, "a-1")
    reg.touch(tmp_path, "a-1")

    assert writes == ["registry.json"]


def test_touch_unregistered_agent_writes_nothing(tmp_path, monkeypatch):
    from common import registry as reg

    def fail_write(path, payload):
        raise AssertionError("must not rewrite registry for unknown agent")

    monkeypatch.setattr(reg.atomicio, "write_json_atomic", fail_write)
    reg.touch(tmp_path, "ghost-9")


def test_load_cached_hits_between_writes(tmp_path, monkeypatch):
    from common import registry as reg

    reg.upsert(tmp_path, "a-1", {"cli": "claude"})
    reads = []
    real_load = reg.load
    monkeypatch.setattr(reg, "load", lambda root, on_corrupt=None: reads.append(1) or real_load(root, on_corrupt))
    monkeypatch.setattr(reg, "_PAYLOAD_CACHE", {})

    assert reg.get(tmp_path, "a-1")["cli"] == "claude"
    assert reg.get(tmp_path, "a-1")["cli"] == "claude"
    assert len(reads) == 1

    reg.upsert(tmp_path, "a-2", {"cli": "pi"})
    reads.clear()
    assert reg.get(tmp_path, "a-2")["cli"] == "pi"
    assert len(reads) == 1


def test_touch_write_invalidates_payload_cache(tmp_path, monkeypatch):
    from common import registry as reg

    reg.upsert(tmp_path, "a-1", {"cli": "claude"})
    monkeypatch.setattr(reg, "_touch_last_seen_at", {})
    monkeypatch.setattr(reg, "_PAYLOAD_CACHE", {})
    before = reg.get(tmp_path, "a-1")["last_seen"]
    reg._touch_last_seen_at.clear()
    import time as time_mod

    reg._touch_last_seen_at["a-1"] = time_mod.time() - reg.TOUCH_THROTTLE_SECONDS - 1
    reg.touch(tmp_path, "a-1")
    assert reg.get(tmp_path, "a-1")["last_seen"] > before
