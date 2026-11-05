import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import federation, peers, registry

pull_peer = federation.pull_peer


def test_pull_peer_merges_records_with_alias(tmp_path, monkeypatch):
    remote_registry = {
        "agents": {
            "claude-node-1-a2a-mailbox": {"agent_id": "claude-node-1-a2a-mailbox", "pane_id": "%5"},
            "not-a-dict": "junk",
        }
    }
    monkeypatch.setattr(
        "common.sshio.read_remote_json_status",
        lambda alias, rel: ("ok", remote_registry) if alias == "host-b" else ("unreachable", None),
    )
    monkeypatch.setattr("common.sshio.read_remote_queue_msgs", lambda alias: ("ok", []))
    result = pull_peer(tmp_path, "host-b")
    assert result == {"peer": "host-b", "ok": True, "merged": 1, "pulled": 0, "status": "ok"}

    merged = registry.load(tmp_path)["agents"]["claude-node-1-a2a-mailbox"]
    assert merged["ssh_alias"] == "host-b"


def test_pull_peer_merges_peer_own_stamped_records(tmp_path, monkeypatch):
    remote_registry = {
        "agents": {
            "claude-host-b-a2a-mailbox": {"agent_id": "claude-host-b-a2a-mailbox", "ssh_alias": "host-b"},
        }
    }
    monkeypatch.setattr("common.sshio.read_remote_json_status", lambda alias, rel: ("ok", remote_registry))
    result = pull_peer(tmp_path, "host-b")
    assert result["merged"] == 1
    assert registry.load(tmp_path)["agents"]["claude-host-b-a2a-mailbox"]["ssh_alias"] == "host-b"


def test_pull_peer_skips_transit_records(tmp_path, monkeypatch):
    remote_registry = {
        "agents": {
            "pi-host-a-a2a-mailbox": {"agent_id": "pi-host-a-a2a-mailbox", "pane_id": "%3"},
            "claude-host-b-a2a-mailbox": {
                "agent_id": "claude-host-b-a2a-mailbox",
                "ssh_alias": "host-b",
            },
        }
    }
    monkeypatch.setattr("common.sshio.read_remote_json_status", lambda alias, rel: ("ok", remote_registry))
    result = pull_peer(tmp_path, "host-a")
    assert result["merged"] == 1
    agents = registry.load(tmp_path)["agents"]
    assert "pi-host-a-a2a-mailbox" in agents
    assert "claude-host-b-a2a-mailbox" not in agents


def test_pull_peer_unreachable_reports_not_ok(tmp_path, monkeypatch):
    monkeypatch.setattr("common.sshio.read_remote_json_status", lambda alias, rel: ("unreachable", None))
    assert pull_peer(tmp_path, "down-host") == {"peer": "down-host", "ok": False, "merged": 0, "pulled": 0, "status": "unreachable"}


def inbound(to, msg_id, injected):
    return {"msg_id": msg_id, "ack_id": f"ack-{msg_id}", "from": "claude-host-b-a2a-mailbox",
            "to": to, "body": f"body {msg_id}", "hop": 1, "created_at": 1.0,
            "wake_text": "wake", "last_injected_at": injected}


def test_pull_peer_repatriates_injected_inbound_mail(tmp_path, monkeypatch):
    registry.upsert(tmp_path, "claude-host-a-a2a-mailbox", {"agent_id": "claude-host-a-a2a-mailbox"})
    monkeypatch.setattr("common.sshio.read_remote_json_status", lambda alias, rel: ("ok", {"agents": {}}))
    monkeypatch.setattr(
        "common.sshio.read_remote_queue_msgs",
        lambda alias: (
            "ok",
            [
                inbound("claude-host-a-a2a-mailbox", "rep00000001", 100.0),
                inbound("claude-host-a-a2a-mailbox", "rep00000002", 0.0),
                inbound("claude-host-b-a2a-mailbox", "rep00000003", 100.0),
            ],
        ),
    )
    result = pull_peer(tmp_path, "host-b")
    assert result["pulled"] == 1
    from common import storage

    assert storage.read_msg(tmp_path, "claude-host-a-a2a-mailbox", "rep00000001") is not None
    assert storage.read_msg(tmp_path, "claude-host-a-a2a-mailbox", "rep00000002") is None


def test_pull_peer_skips_repatriated_already_local(tmp_path, monkeypatch):
    registry.upsert(tmp_path, "claude-host-a-a2a-mailbox", {"agent_id": "claude-host-a-a2a-mailbox"})
    monkeypatch.setattr("common.sshio.read_remote_json_status", lambda alias, rel: ("ok", {"agents": {}}))
    monkeypatch.setattr(
        "common.sshio.read_remote_queue_msgs",
        lambda alias: ("ok", [inbound("claude-host-a-a2a-mailbox", "rep00000001", 100.0)]),
    )
    pull_peer(tmp_path, "host-b")
    again = pull_peer(tmp_path, "host-b")
    assert again["pulled"] == 0
    (tmp_path / "history").mkdir(exist_ok=True)
    from common import storage

    storage.enqueue(tmp_path, inbound("claude-host-a-a2a-mailbox", "rep00000009", 100.0))
    storage.archive_msg(tmp_path, "claude-host-a-a2a-mailbox", "rep00000009")
    monkeypatch.setattr(
        "common.sshio.read_remote_queue_msgs",
        lambda alias: ("ok", [inbound("claude-host-a-a2a-mailbox", "rep00000009", 100.0)]),
    )
    assert pull_peer(tmp_path, "host-b")["pulled"] == 0


def test_load_peers_reads_json(tmp_path):
    (tmp_path / "peers.json").write_text('{"peers": ["host-b", ""]}')
    assert peers.load_peers(tmp_path) == ["host-b"]


def test_load_peers_missing_file(tmp_path):
    assert peers.load_peers(tmp_path) == []


def test_pull_skips_queue_anchored_recipient(tmp_path, monkeypatch):
    from common import codexq, federation, registry as reg_mod

    anchored = {
        "agent_id": "codex-host-b-000-host-c",
        "cli": "codex",
        "pane_id": "",
        "spawn_cmd": None,
        "ssh_alias": "host-b",
        "codex_bin": "/mnt/c/codex.exe",
        "codex_home": "/mnt/c/.codex",
        "codex_thread": "aaaa5c8b-07a4-7f61-a73c-312c7a2d915e",
    }
    reg_mod.upsert(tmp_path, "codex-host-b-000-host-c", anchored)
    envelope = {
        "msg_id": "pq0001",
        "to": "codex-host-b-000-host-c",
        "last_injected_at": 100.0,
        "body": "已注入的 queue 收件人信件",
    }
    monkeypatch.setattr(
        federation.sshio,
        "read_remote_queue_msgs",
        lambda alias: ("ok", [dict(envelope)]),
    )
    assert federation.pull_inbound_msgs(tmp_path, "host-b", {"codex-host-b-000-host-c"}) == 0
    assert federation.storage.read_msg(tmp_path, "codex-host-b-000-host-c", "pq0001") is None


def test_pull_skips_failed_terminal_copy(tmp_path, monkeypatch):
    from common import federation, storage

    registry.upsert(tmp_path, "claude-host-a-a2a-mailbox", {"agent_id": "claude-host-a-a2a-mailbox"})
    storage.enqueue(tmp_path, inbound("claude-host-a-a2a-mailbox", "fail00000001", 100.0))
    storage.mark_failed(tmp_path, "claude-host-a-a2a-mailbox", "fail00000001")
    monkeypatch.setattr(
        "common.sshio.read_remote_queue_msgs",
        lambda alias: ("ok", [inbound("claude-host-a-a2a-mailbox", "fail00000001", 100.0)]),
    )
    assert federation.pull_inbound_msgs(tmp_path, "host-b", {"claude-host-a-a2a-mailbox"}) == 0
    assert storage.read_msg(tmp_path, "claude-host-a-a2a-mailbox", "fail00000001") is None


def test_pull_survives_poison_envelope_and_pulls_rest(tmp_path, monkeypatch):
    from common import federation, storage

    registry.upsert(tmp_path, "claude-host-a-a2a-mailbox", {"agent_id": "claude-host-a-a2a-mailbox"})
    poisoned = inbound("claude-host-a-a2a-mailbox", "poi00000001", "not-a-number")
    healthy = inbound("claude-host-a-a2a-mailbox", "hea00000001", 100.0)
    monkeypatch.setattr("common.sshio.read_remote_json_status", lambda alias, rel: ("ok", {"agents": {}}))
    monkeypatch.setattr("common.sshio.read_remote_queue_msgs", lambda alias: ("ok", [poisoned, healthy]))
    result = pull_peer(tmp_path, "host-b")
    assert result["ok"] is True and result["pulled"] == 1
    assert storage.read_msg(tmp_path, "claude-host-a-a2a-mailbox", "hea00000001") is not None
    assert storage.read_msg(tmp_path, "claude-host-a-a2a-mailbox", "poi00000001") is None


def test_pull_peer_settles_mirror_after_origin_archive(tmp_path, monkeypatch):
    import time as time_mod

    from common import storage

    ME = "claude-host-a-a2a-mailbox"
    registry.upsert(tmp_path, ME, {"agent_id": ME, "cli": "claude", "pane_id": "%46"})
    mirror = {
        "msg_id": "aa0000000001", "ack_id": "ack-aa0000000001", "from": "hub", "to": ME,
        "body": "投递失败通知", "hop": 1, "created_at": 1.0, "wake_text": "wake aa0000000001",
        "last_injected_at": 100.0,
    }
    storage.enqueue(tmp_path, mirror)

    def remote_status(alias, rel):
        if rel.endswith("registry.json"):
            return ("ok", {"agents": {}})
        if rel.endswith("history/aa0000000001.json"):
            return ("ok", {"msg_id": "aa0000000001"})
        return ("missing", None)

    monkeypatch.setattr("common.sshio.read_remote_json_status", remote_status)
    monkeypatch.setattr("common.sshio.read_remote_queue_msgs", lambda alias: ("ok", []))

    pull_peer(tmp_path, "host-b")

    assert storage.read_msg(tmp_path, ME, "aa0000000001") is None
    assert (tmp_path / "history" / "aa0000000001.json").exists()


def test_pull_peer_keeps_mirror_while_in_flight(tmp_path, monkeypatch):
    from common import storage

    ME = "claude-host-a-a2a-mailbox"
    registry.upsert(tmp_path, ME, {"agent_id": ME, "cli": "claude", "pane_id": "%46"})
    mirror = {
        "msg_id": "bb0000000001", "ack_id": "ack-bb0000000001", "from": "hub", "to": ME,
        "body": "在途通知", "hop": 1, "created_at": 1.0, "wake_text": "wake bb0000000001",
        "last_injected_at": 100.0,
    }
    storage.enqueue(tmp_path, mirror)
    monkeypatch.setattr("common.sshio.read_remote_json_status", lambda alias, rel: ("ok", {"agents": {}}) if rel.endswith("registry.json") else ("missing", None))
    monkeypatch.setattr("common.sshio.read_remote_queue_msgs", lambda alias: ("ok", [dict(mirror)]))

    pull_peer(tmp_path, "host-b")

    assert storage.read_msg(tmp_path, ME, "bb0000000001") is not None


def test_pull_peer_marks_mirror_failed(tmp_path, monkeypatch):
    from common import storage

    ME = "claude-host-a-a2a-mailbox"
    registry.upsert(tmp_path, ME, {"agent_id": ME, "cli": "claude", "pane_id": "%46"})
    mirror = {
        "msg_id": "cc0000000001", "ack_id": "ack-cc0000000001", "from": "hub", "to": ME,
        "body": "失败通知", "hop": 1, "created_at": 1.0, "wake_text": "wake cc0000000001",
        "last_injected_at": 100.0,
    }
    storage.enqueue(tmp_path, mirror)

    def remote_status(alias, rel):
        if rel.endswith("registry.json"):
            return ("ok", {"agents": {}})
        if rel.endswith("cc0000000001.failed"):
            return ("ok", {"msg_id": "cc0000000001"})
        return ("missing", None)

    monkeypatch.setattr("common.sshio.read_remote_json_status", remote_status)
    monkeypatch.setattr("common.sshio.read_remote_queue_msgs", lambda alias: ("ok", []))

    pull_peer(tmp_path, "host-b")

    assert (tmp_path / "queue" / ME / "cc0000000001.failed").exists()
