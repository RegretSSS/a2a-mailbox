import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import storage


def envelope(msg_id, to_id, ack_id=None, created_at=1.0, from_id="claude-h-1"):
    return {
        "msg_id": msg_id,
        "ack_id": ack_id or f"ack-{msg_id}",
        "from": from_id,
        "to": to_id,
        "body": "去哪读: memory/MEMORY.md",
        "hop": 1,
        "created_at": created_at,
        "wake_text": f"[A2A] from={from_id} id={msg_id} ack={ack_id or f'ack-{msg_id}'}\n去哪读: memory/MEMORY.md",
    }


def test_new_ids_are_distinct_and_paired():
    first_msg, first_ack = storage.new_ids()
    second_msg, second_ack = storage.new_ids()
    assert first_msg != second_msg
    assert first_ack == f"ack-{first_msg}"
    assert second_ack == f"ack-{second_msg}"


def test_enqueue_read_and_list_order(tmp_path):
    storage.enqueue(tmp_path, envelope("m2", "codex-h-2", created_at=2.0))
    storage.enqueue(tmp_path, envelope("m1", "codex-h-2", created_at=1.0))
    listed = storage.list_queue(tmp_path, "codex-h-2")
    assert [item["msg_id"] for item in listed] == ["m1", "m2"]
    read_back = storage.read_msg(tmp_path, "codex-h-2", "m1")
    assert read_back["body"] == "去哪读: memory/MEMORY.md"


def test_find_msg_across_queues(tmp_path):
    storage.enqueue(tmp_path, envelope("m1", "codex-h-2"))
    storage.enqueue(tmp_path, envelope("m2", "pi-h-3"))
    found = storage.find_msg(tmp_path, "m2")
    assert found is not None and found["to"] == "pi-h-3"
    assert storage.find_msg(tmp_path, "missing") is None


def test_write_ack_is_idempotent(tmp_path):
    storage.write_ack(tmp_path, "ack-m1", "codex-h-2")
    first = (tmp_path / "acks" / "ack-m1").read_text()
    storage.write_ack(tmp_path, "ack-m1", "codex-h-2")
    second = (tmp_path / "acks" / "ack-m1").read_text()
    assert first == second
    assert storage.ack_exists(tmp_path, "ack-m1")
    assert not storage.ack_exists(tmp_path, "ack-m2")


def test_find_ack_target_returns_owner(tmp_path):
    storage.enqueue(tmp_path, envelope("m1", "codex-h-2"))
    target = storage.find_ack_target(tmp_path, "ack-m1")
    assert target is not None and target["to"] == "codex-h-2"
    assert storage.find_ack_target(tmp_path, "ack-nope") is None


def test_discard_and_mark_failed(tmp_path):
    storage.enqueue(tmp_path, envelope("m1", "codex-h-2"))
    storage.discard_msg(tmp_path, "codex-h-2", "m1")
    assert storage.list_queue(tmp_path, "codex-h-2") == []
    storage.enqueue(tmp_path, envelope("m2", "codex-h-2"))
    failed_path = storage.mark_failed(tmp_path, "codex-h-2", "m2")
    assert failed_path.name == "m2.failed"
    assert failed_path.exists()
    assert storage.list_queue(tmp_path, "codex-h-2") == []


def test_rate_gate_blocks_at_window_cap(tmp_path):
    results = [storage.rate_gate(tmp_path, "claude-h-1", "codex-h-2", now=1000.0) for _ in range(12)]
    assert all(allowed for allowed, _ in results[:10])
    assert not any(allowed for allowed, _ in results[10:])


def test_rate_gate_reports_retry_after(tmp_path):
    for _ in range(10):
        storage.rate_gate(tmp_path, "claude-h-1", "codex-h-2", now=1000.0)
    allowed, retry_after = storage.rate_gate(tmp_path, "claude-h-1", "codex-h-2", now=1005.0)
    assert not allowed
    assert 54.0 <= retry_after <= 56.0


def test_rate_gate_prunes_expired_stamps(tmp_path):
    for _ in range(10):
        storage.rate_gate(tmp_path, "claude-h-1", "codex-h-2", now=1000.0)
    assert not storage.rate_gate(tmp_path, "claude-h-1", "codex-h-2", now=1000.0)[0]
    assert storage.rate_gate(tmp_path, "claude-h-1", "codex-h-2", now=1061.0)[0]


def test_rate_gate_truncates_ledger_in_lock_span(tmp_path):
    ledger = tmp_path / "rates" / "claude-h-1__codex-h-2.ledger"
    ledger.parent.mkdir(parents=True)
    ledger.write_text("\n".join(str(900.0 + n) for n in range(50)) + "\n")
    allowed, _ = storage.rate_gate(tmp_path, "claude-h-1", "codex-h-2", now=1000.0)
    assert allowed
    kept = [float(line) for line in ledger.read_text().splitlines()]
    assert len(kept) == 10
    assert kept[-1] == 1000.0
    assert all(stamp >= 941.0 for stamp in kept)


def test_rate_gate_symmetric_pair_shared(tmp_path):
    for _ in range(10):
        storage.rate_gate(tmp_path, "claude-h-1", "codex-h-2", now=1000.0)
    assert storage.rate_gate(tmp_path, "claude-h-1", "pi-h-3", now=1000.0)[0]
    allowed, retry_after = storage.rate_gate(tmp_path, "codex-h-2", "claude-h-1", now=1000.0)
    assert not allowed and retry_after > 0


def test_rate_gate_pair_key_undirected():
    assert storage.pair_key("b-agent", "a-agent") == storage.pair_key("a-agent", "b-agent")


def test_online_map_roundtrip(tmp_path):
    storage.write_online(tmp_path, {"a": True, "b": False}, 100.0)
    assert storage.load_online(tmp_path) == {"a": True, "b": False}
    storage.write_online(tmp_path, {}, 101.0)
    assert storage.load_online(tmp_path) == {}


def test_rcpt_global_claim_across_agent_dirs(tmp_path):
    from common import nativebox

    nativebox.write_rcpt(tmp_path, "pi-host-b-pi-agent-kit", "ab0000000001", 100.0)

    assert nativebox.rcpt_exists(tmp_path, "pi-host-a-pi-agent-kit", "ab0000000001")
    assert not nativebox.rcpt_exists(tmp_path, "pi-host-a-pi-agent-kit", "ab0000000002")


def test_find_ack_target_reads_only_derived_file(tmp_path, monkeypatch):
    from common import storage

    for agent_id in ("a-1", "b-2", "c-3"):
        storage.enqueue(tmp_path, {"msg_id": f"m{agent_id[0]}", "ack_id": f"ack-m{agent_id[0]}", "to": agent_id, "from": "x-0", "body": "hi", "created_at": 1.0})
    reads = []
    real_read = storage.read_json

    def counting_read(path):
        reads.append(path.name)
        return real_read(path)

    monkeypatch.setattr(storage, "read_json", counting_read)
    monkeypatch.setattr(storage, "_ENVELOPE_CACHE", {})

    found = storage.find_ack_target(tmp_path, "ack-mb")
    assert found is not None and found["to"] == "b-2"
    assert reads == ["mb.msg"]


def test_find_ack_target_falls_back_to_full_scan_for_custom_ack(tmp_path):
    from common import storage

    storage.enqueue(tmp_path, {"msg_id": "m1", "ack_id": "custom-receipt", "to": "b-2", "from": "x-0", "body": "hi", "created_at": 1.0})
    assert storage.find_ack_target(tmp_path, "custom-receipt")["msg_id"] == "m1"
    assert storage.find_ack_target(tmp_path, "ack-nothere") is None


def test_envelope_cache_invalidates_on_rewrite(tmp_path, monkeypatch):
    from common import storage

    storage.enqueue(tmp_path, {"msg_id": "m1", "ack_id": "ack-m1", "to": "a-1", "from": "x-0", "body": "one", "created_at": 1.0})
    first = storage.list_queue(tmp_path, "a-1")[0]
    assert first["body"] == "one"
    path = storage.msg_path(tmp_path, "a-1", "m1")
    envelope = storage.read_json(path)
    envelope["body"] = "two"
    storage.atomicio.write_json_atomic(path, envelope)
    assert storage.list_queue(tmp_path, "a-1")[0]["body"] == "two"


def test_list_queue_reports_unreadable_msg(tmp_path):
    from common import storage

    storage.enqueue(tmp_path, {"msg_id": "m1", "ack_id": "ack-m1", "to": "a-1", "from": "x-0", "body": "ok", "created_at": 1.0})
    broken = storage.queue_dir(tmp_path, "a-1") / "m2.msg"
    broken.write_text("{not json")
    reported = []
    envelopes = storage.list_queue(tmp_path, "a-1", on_unreadable=reported.append)
    assert [e["msg_id"] for e in envelopes] == ["m1"]
    assert [p.name for p in reported] == ["m2.msg"]
