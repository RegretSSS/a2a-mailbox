import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import federation, peers, registry

pull_peer = federation.pull_peer


def snapshot(registry=None, queue=(), settled=None):
    payload = {
        "registry": registry if registry is not None else {"agents": {}},
        "queue": list(queue),
        "settled": settled or {},
    }
    return ("ok", payload)


def test_pull_peer_merges_records_with_alias(tmp_path, monkeypatch):
    remote_registry = {
        "agents": {
            "claude-host-d-a2a-mailbox": {"agent_id": "claude-host-d-a2a-mailbox", "pane_id": "%5"},
            "not-a-dict": "junk",
        }
    }

    def fake_snapshot(alias, probe_ids):
        return snapshot(remote_registry) if alias == "host-b" else ("unreachable", None)

    monkeypatch.setattr("common.sshio.read_remote_federation_snapshot", fake_snapshot)
    result = pull_peer(tmp_path, "host-b")
    assert result == {"peer": "host-b", "ok": True, "merged": 1, "pulled": 0, "status": "ok"}

    merged = registry.load(tmp_path)["agents"]["claude-host-d-a2a-mailbox"]
    assert merged["ssh_alias"] == "host-b"


def test_pull_peer_merges_peer_own_stamped_records(tmp_path, monkeypatch):
    remote_registry = {
        "agents": {
            "claude-host-b-a2a-mailbox": {"agent_id": "claude-host-b-a2a-mailbox", "ssh_alias": "host-b"},
        }
    }
    monkeypatch.setattr("common.sshio.read_remote_federation_snapshot", lambda alias, probe_ids: snapshot(remote_registry))
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
    monkeypatch.setattr("common.sshio.read_remote_federation_snapshot", lambda alias, probe_ids: snapshot(remote_registry))
    result = pull_peer(tmp_path, "host-a")
    assert result["merged"] == 1
    agents = registry.load(tmp_path)["agents"]
    assert "pi-host-a-a2a-mailbox" in agents
    assert "claude-host-b-a2a-mailbox" not in agents


def test_pull_peer_unreachable_reports_not_ok(tmp_path, monkeypatch):
    monkeypatch.setattr("common.sshio.read_remote_federation_snapshot", lambda alias, probe_ids: ("unreachable", None))
    assert pull_peer(tmp_path, "down-host") == {"peer": "down-host", "ok": False, "merged": 0, "pulled": 0, "status": "unreachable"}


def inbound(to, msg_id, injected):
    return {"msg_id": msg_id, "ack_id": f"ack-{msg_id}", "from": "claude-host-b-a2a-mailbox",
            "to": to, "body": f"body {msg_id}", "hop": 1, "created_at": 1.0,
            "wake_text": "wake", "last_injected_at": injected}


def test_pull_peer_repatriates_injected_inbound_mail(tmp_path, monkeypatch):
    registry.upsert(tmp_path, "claude-host-a-a2a-mailbox", {"agent_id": "claude-host-a-a2a-mailbox"})
    monkeypatch.setattr(
        "common.sshio.read_remote_federation_snapshot",
        lambda alias, probe_ids: snapshot(queue=[
            inbound("claude-host-a-a2a-mailbox", "rep00000001", 100.0),
            inbound("claude-host-a-a2a-mailbox", "rep00000002", 0.0),
            inbound("claude-host-b-a2a-mailbox", "rep00000003", 100.0),
        ]),
    )
    result = pull_peer(tmp_path, "host-b")
    assert result["pulled"] == 1
    from common import storage

    assert storage.read_msg(tmp_path, "claude-host-a-a2a-mailbox", "rep00000001") is not None
    assert storage.read_msg(tmp_path, "claude-host-a-a2a-mailbox", "rep00000002") is None


def test_pull_peer_skips_repatriated_already_local(tmp_path, monkeypatch):
    registry.upsert(tmp_path, "claude-host-a-a2a-mailbox", {"agent_id": "claude-host-a-a2a-mailbox"})
    monkeypatch.setattr(
        "common.sshio.read_remote_federation_snapshot",
        lambda alias, probe_ids: snapshot(queue=[inbound("claude-host-a-a2a-mailbox", "rep00000001", 100.0)]),
    )
    pull_peer(tmp_path, "host-b")
    again = pull_peer(tmp_path, "host-b")
    assert again["pulled"] == 0
    (tmp_path / "history").mkdir(exist_ok=True)
    from common import storage

    storage.enqueue(tmp_path, inbound("claude-host-a-a2a-mailbox", "rep00000009", 100.0))
    storage.archive_msg(tmp_path, "claude-host-a-a2a-mailbox", "rep00000009")
    monkeypatch.setattr(
        "common.sshio.read_remote_federation_snapshot",
        lambda alias, probe_ids: snapshot(queue=[inbound("claude-host-a-a2a-mailbox", "rep00000009", 100.0)]),
    )
    assert pull_peer(tmp_path, "host-b")["pulled"] == 0


def test_load_peers_reads_json(tmp_path):
    (tmp_path / "peers.json").write_text('{"peers": ["host-b", ""]}')
    assert peers.load_peers(tmp_path) == ["host-b"]


def test_load_peers_missing_file(tmp_path):
    assert peers.load_peers(tmp_path) == []


def test_pull_skips_queue_anchored_recipient(tmp_path, monkeypatch):
    from common import codexq, registry as reg_mod

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
    assert federation.pull_inbound_msgs(tmp_path, "host-b", {"codex-host-b-000-host-c"}, [dict(envelope)]) == 0
    assert federation.storage.read_msg(tmp_path, "codex-host-b-000-host-c", "pq0001") is None


def test_pull_skips_failed_terminal_copy(tmp_path, monkeypatch):
    from common import federation, storage

    registry.upsert(tmp_path, "claude-host-a-a2a-mailbox", {"agent_id": "claude-host-a-a2a-mailbox"})
    storage.enqueue(tmp_path, inbound("claude-host-a-a2a-mailbox", "fail00000001", 100.0))
    storage.mark_failed(tmp_path, "claude-host-a-a2a-mailbox", "fail00000001")
    assert federation.pull_inbound_msgs(
        tmp_path, "host-b", {"claude-host-a-a2a-mailbox"}, [inbound("claude-host-a-a2a-mailbox", "fail00000001", 100.0)]
    ) == 0
    assert storage.read_msg(tmp_path, "claude-host-a-a2a-mailbox", "fail00000001") is None


def test_pull_survives_poison_envelope_and_pulls_rest(tmp_path, monkeypatch):
    from common import federation, storage

    registry.upsert(tmp_path, "claude-host-a-a2a-mailbox", {"agent_id": "claude-host-a-a2a-mailbox"})
    poisoned = inbound("claude-host-a-a2a-mailbox", "poi00000001", "not-a-number")
    healthy = inbound("claude-host-a-a2a-mailbox", "hea00000001", 100.0)
    monkeypatch.setattr(
        "common.sshio.read_remote_federation_snapshot",
        lambda alias, probe_ids: snapshot(queue=[poisoned, healthy]),
    )
    result = pull_peer(tmp_path, "host-b")
    assert result["ok"] is True and result["pulled"] == 1
    assert storage.read_msg(tmp_path, "claude-host-a-a2a-mailbox", "hea00000001") is not None
    assert storage.read_msg(tmp_path, "claude-host-a-a2a-mailbox", "poi00000001") is None


def test_pull_peer_settles_mirror_after_origin_archive(tmp_path, monkeypatch):
    from common import storage

    ME = "claude-host-a-a2a-mailbox"
    registry.upsert(tmp_path, ME, {"agent_id": ME, "cli": "claude", "pane_id": "%46"})
    mirror = {
        "msg_id": "aa0000000001", "ack_id": "ack-aa0000000001", "from": "hub", "to": ME,
        "body": "投递失败通知", "hop": 1, "created_at": 1.0, "wake_text": "wake aa0000000001",
        "last_injected_at": 100.0,
    }
    storage.enqueue(tmp_path, mirror)
    monkeypatch.setattr(
        "common.sshio.read_remote_federation_snapshot",
        lambda alias, probe_ids: snapshot(settled={"aa0000000001": "archived"}),
    )

    pull_peer(tmp_path, "host-b")

    assert storage.read_msg(tmp_path, ME, "aa0000000001") is None
    assert (tmp_path / "history" / "aa0000000001.json").exists()


def test_settle_spares_relayed_inflight_copy(tmp_path, monkeypatch):
    from common import storage

    ME = "pi-host-a-pi-agent-kit"
    registry.upsert(tmp_path, ME, {"agent_id": ME, "cli": "pi", "pane_id": "%22"})
    relayed = {
        "msg_id": "cc0000000001", "ack_id": "ack-cc0000000001", "from": "claude-host-a-a2a-mailbox", "to": ME,
        "body": "relay 直投在途", "hop": 1, "created_at": 1.0, "wake_text": "wake cc0000000001",
        "last_injected_at": 100.0, "home_relay_first_at": 99.0, "home_relay_last_try": 99.0,
    }
    storage.enqueue(tmp_path, relayed)
    monkeypatch.setattr(
        "common.sshio.read_remote_federation_snapshot",
        lambda alias, probe_ids: snapshot(settled={"cc0000000001": "archived"}),
    )

    pull_peer(tmp_path, "host-a")

    assert storage.read_msg(tmp_path, ME, "cc0000000001") is not None
    assert not (tmp_path / "history" / "cc0000000001.json").exists()


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
    monkeypatch.setattr(
        "common.sshio.read_remote_federation_snapshot",
        lambda alias, probe_ids: snapshot(queue=[dict(mirror)]),
    )

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
    monkeypatch.setattr(
        "common.sshio.read_remote_federation_snapshot",
        lambda alias, probe_ids: snapshot(settled={"cc0000000001": "failed"}),
    )

    pull_peer(tmp_path, "host-b")

    assert (tmp_path / "queue" / ME / "cc0000000001.failed").exists()


def test_pull_peer_settles_only_probe_ids_from_local_queue(tmp_path, monkeypatch):
    seen_probes = []

    def fake_snapshot(alias, probe_ids):
        seen_probes.append(list(probe_ids))
        return snapshot(settled={"aa0000000001": "archived"})

    monkeypatch.setattr("common.sshio.read_remote_federation_snapshot", fake_snapshot)
    pull_peer(tmp_path, "host-b")
    assert seen_probes == [[]]

    from common import storage

    registry.upsert(tmp_path, "claude-host-a-a2a-mailbox", {"agent_id": "claude-host-a-a2a-mailbox"})
    storage.enqueue(tmp_path, inbound("claude-host-a-a2a-mailbox", "aa0000000001", 100.0))
    pull_peer(tmp_path, "host-b")
    assert seen_probes[-1] == ["aa0000000001"]
