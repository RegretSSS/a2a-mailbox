import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import msgfmt, paths, registry, storage, tmuxio

_SPEC = importlib.util.spec_from_file_location(
    "mailbox_mcp", Path(__file__).resolve().parent.parent / "mcp" / "mailbox_mcp.py"
)
mailbox_mcp = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mailbox_mcp)


REAL_BOOT_HUB = mailbox_mcp.boot_hub_if_absent


@pytest.fixture(autouse=True)
def hub_boot_off(monkeypatch):
    monkeypatch.setattr(mailbox_mcp, "boot_hub_if_absent", lambda root: None)

ALICE = "claude-h-1"
BOB = "codex-h-2"


def load(text: str) -> dict:
    return json.loads(text)


def register_both(tmp_path):
    registry.upsert(tmp_path, ALICE, {"cli": "claude", "pane_id": "%1", "pane_pid": "100"})
    registry.upsert(tmp_path, BOB, {"cli": "codex", "pane_id": "%2", "pane_pid": "200"})


def queued(tmp_path, to, msg_id):
    envelope = storage.read_msg(tmp_path, to, msg_id)
    assert envelope is not None
    return envelope


def test_self_register_writes_record(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    (tmp_path / "proj").mkdir()
    monkeypatch.chdir(tmp_path / "proj")
    monkeypatch.setattr(mailbox_mcp.detect, "current_pane_id", lambda: "%7")
    monkeypatch.setattr(mailbox_mcp.detect, "detect_cli", lambda: "claude")
    monkeypatch.setattr(mailbox_mcp.detect, "local_host", lambda: "box")
    monkeypatch.setattr(mailbox_mcp.detect, "tailscale_self_name", lambda: "")
    monkeypatch.setattr(mailbox_mcp.detect, "tailnet_host", lambda: "100.1.2.3")
    monkeypatch.setattr(mailbox_mcp.tmuxio, "pane_pid", lambda pane, ssh=None: "4242")

    record = mailbox_mcp.self_register()

    assert record["agent_id"] == "claude-box-proj"
    assert record["pane_pid"] == "4242"
    assert record["tailnet_host"] == "100.1.2.3"
    assert registry.get(tmp_path, "claude-box-proj")["cli"] == "claude"


def test_self_register_paneless(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    monkeypatch.setenv("A2A_PANELESS", "1")
    monkeypatch.delenv("TMUX_PANE", raising=False)
    monkeypatch.setattr(mailbox_mcp.detect, "current_pane_id", lambda: "")
    monkeypatch.setattr(mailbox_mcp.detect, "detect_cli", lambda: "codex")
    monkeypatch.setattr(mailbox_mcp.detect, "local_host", lambda: "box")
    monkeypatch.setattr(mailbox_mcp.detect, "tailscale_self_name", lambda: "")
    monkeypatch.setattr(mailbox_mcp.detect, "tailnet_host", lambda: "")

    record = mailbox_mcp.self_register()

    assert record["agent_id"].startswith("codex-box-")
    assert record["pane_id"] == ""
    assert record["pane_pid"] == ""


def test_spawn_cmd_from_env(monkeypatch):
    monkeypatch.delenv("A2A_SPAWN_CMD", raising=False)
    assert mailbox_mcp.spawn_cmd_from_env() is None
    monkeypatch.setenv("A2A_SPAWN_CMD", "codex exec --json")
    assert mailbox_mcp.spawn_cmd_from_env() == ["codex", "exec", "--json"]
    monkeypatch.setenv("A2A_SPAWN_CMD", "'unterminated")
    assert mailbox_mcp.spawn_cmd_from_env() is None


def test_do_send_happy_path(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    register_both(tmp_path)

    sent = load(mailbox_mcp.do_send(ALICE, BOB, "去哪读: plans/next.md 第3步后继续"))

    assert sent["ok"] is True
    envelope = queued(tmp_path, BOB, sent["msg_id"])
    assert envelope["hop"] == 1
    parsed = msgfmt.parse_wake(envelope["wake_text"])
    assert parsed[0] == ALICE
    assert parsed[1] == envelope["msg_id"]
    assert parsed[2] == envelope["ack_id"]


def test_do_send_clueless_revival_sends_with_hint(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    register_both(tmp_path)

    sent = load(mailbox_mcp.do_send(ALICE, BOB, "继续刚才的任务"))

    assert sent["ok"] is True
    assert "线索文件路径" in sent["hint"]
    assert queued(tmp_path, BOB, sent["msg_id"])["body"] == "继续刚才的任务"


def test_do_send_mood_words_send_with_hint(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    register_both(tmp_path)

    sent = load(mailbox_mcp.do_send(ALICE, BOB, "嗯嗯"))

    assert sent["ok"] is True
    assert "澄清" in sent["hint"]


def test_do_send_rejects_empty_body(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    register_both(tmp_path)

    sent = load(mailbox_mcp.do_send(ALICE, BOB, "   "))

    assert sent["ok"] is False


def test_do_send_rejects_unknown_target(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    register_both(tmp_path)

    sent = load(mailbox_mcp.do_send(ALICE, "ghost-h-9", "去哪读: plans/a.md"))

    assert sent["ok"] is False
    assert "mail_who" in sent["error"]


def test_do_send_reply_chain_increments_hop(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    register_both(tmp_path)
    first = load(mailbox_mcp.do_send(ALICE, BOB, "去哪读: plans/a.md"))
    reply = load(mailbox_mcp.do_send(BOB, ALICE, "去哪读: plans/b.md", in_reply_to=first["msg_id"]))

    assert reply["ok"] is True
    assert queued(tmp_path, ALICE, reply["msg_id"])["hop"] == 2


def test_do_send_deep_hop_observed_not_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    register_both(tmp_path)
    deep = queued_envelope_with_hop(tmp_path, msgfmt.HOP_WARNING_THRESHOLD)
    chained = load(mailbox_mcp.do_send(BOB, ALICE, "去哪读: plans/y.md", in_reply_to=deep["msg_id"]))

    assert chained["ok"] is True
    assert "hop_warning" in chained
    assert queued(tmp_path, ALICE, chained["msg_id"])["hop"] == msgfmt.HOP_WARNING_THRESHOLD + 1


def queued_envelope_with_hop(tmp_path, hop):
    from common import msgfmt as msgfmt_module

    msg_id = f"deep{hop:04d}000001"
    envelope = {
        "msg_id": msg_id,
        "ack_id": f"ack-{msg_id}",
        "from": ALICE,
        "to": BOB,
        "body": "去哪读: plans/deep.md",
        "hop": hop,
        "created_at": 1.0,
        "wake_text": msgfmt_module.compose_wake(ALICE, msg_id, "去哪读: plans/deep.md"),
    }
    storage.enqueue(tmp_path, envelope)
    return envelope


def test_do_send_rejects_unknown_in_reply_to(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    register_both(tmp_path)

    sent = load(mailbox_mcp.do_send(ALICE, BOB, "去哪读: plans/a.md", in_reply_to="nope"))

    assert sent["ok"] is False


def test_do_send_resolves_cross_host_in_reply_to(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    register_both(tmp_path)
    (tmp_path / "peers.json").write_text('{"peers": ["host-b"]}')
    remote_origin = {
        "msg_id": "m-remote-1",
        "ack_id": "ack-m-remote-1",
        "from": "claude-host-b-ws",
        "to": BOB,
        "hop": 3,
    }

    def fake_read(alias, rel):
        assert alias == "host-b"
        assert rel == ".agents-mailbox/queue/*/m-remote-1.msg"
        return remote_origin

    monkeypatch.setattr(mailbox_mcp.sshio, "read_remote_json_status", lambda a, r: ("ok", fake_read(a, r)))

    reply = load(mailbox_mcp.do_send(BOB, ALICE, "去哪读: plans/b.md", in_reply_to="m-remote-1"))
    assert reply["ok"] is True
    assert queued(tmp_path, ALICE, reply["msg_id"])["hop"] == 4

    remote_origin["hop"] = msgfmt.HOP_WARNING_THRESHOLD
    exhausted = load(mailbox_mcp.do_send(ALICE, BOB, "去哪读: plans/c.md", in_reply_to="m-remote-1"))
    assert exhausted["ok"] is True
    assert "hop_warning" in exhausted


def test_do_read_falls_back_to_remote_peer_queue(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    register_both(tmp_path)
    (tmp_path / "peers.json").write_text('{"peers": ["host-b"]}')
    remote_envelope = {
        "msg_id": "rm0000000001",
        "ack_id": "ack-rm0000000001",
        "from": "claude-host-b-a2a-mailbox",
        "to": BOB,
        "in_reply_to": "",
        "body": "host-b 腿正文",
        "context": "fed leg",
        "expect_reply": True,
    }
    reads = {"n": 0}

    def fake_read(alias, rel):
        reads["n"] += 1
        if rel == ".agents-mailbox/queue/*/rm0000000001.msg":
            return remote_envelope
        return None

    monkeypatch.setattr(mailbox_mcp.sshio, "read_remote_json_status", lambda a, r: ("ok", fake_read(a, r)))

    payload = load(mailbox_mcp.do_read(BOB, "rm0000000001"))
    assert payload["ok"] is True
    assert payload["body"] == "host-b 腿正文"
    assert payload["expect_reply"] is True
    assert reads["n"] >= 1

    not_mine = dict(remote_envelope, to="someone-else")
    monkeypatch.setattr(
        mailbox_mcp.sshio,
        "read_remote_json_status",
        lambda a, r: ("ok", not_mine if "rm0000000001" in r else None),
    )
    denied = load(mailbox_mcp.do_read(BOB, "rm0000000001"))
    assert denied["ok"] is False


def test_do_send_rate_limited(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    register_both(tmp_path)
    verdicts = [
        load(mailbox_mcp.do_send(ALICE, BOB, f"去哪读: plans/{index}.md"))["ok"]
        for index in range(storage.RATE_MAX_PER_WINDOW + 1)
    ]

    assert all(verdicts[:-1])
    assert verdicts[-1] is False


def test_reply_implies_ack_confirms_origin(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    register_both(tmp_path)
    sent = load(mailbox_mcp.do_send(ALICE, BOB, "去哪读: plans/a.md"))
    origin_msg_id = sent["msg_id"]
    origin_ack_id = queued(tmp_path, BOB, origin_msg_id)["ack_id"]

    reply = load(mailbox_mcp.do_send(BOB, ALICE, "E2E-V2 pi 腿回函OK", in_reply_to=origin_msg_id))

    assert reply["ok"] is True
    assert storage.ack_exists(tmp_path, origin_ack_id)
    assert storage.read_json(storage.ack_path(tmp_path, origin_ack_id))["by"] == BOB


def test_short_receipt_without_in_reply_to_passes(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    register_both(tmp_path)

    reply = load(mailbox_mcp.do_send(BOB, ALICE, "E2E-V2 codex-wsl 腿回函OK"))

    assert reply["ok"] is True


def test_in_reply_to_null_string_treated_as_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    register_both(tmp_path)

    reply = load(mailbox_mcp.do_send(BOB, ALICE, "E2E-V2 codex-win 腿回函OK", in_reply_to="null"))

    assert reply["ok"] is True
    assert load(mailbox_mcp.do_poll(BOB))["messages"] == []


def test_unknown_in_reply_to_error_carries_example(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    register_both(tmp_path)

    reply = load(mailbox_mcp.do_send(BOB, ALICE, "E2E-V2 回函OK", in_reply_to="deadbeef0000"))

    assert reply["ok"] is False
    assert "mail_read" in reply["error"]
    assert "null" in reply["error"]


def test_vague_long_revival_sends_with_hint(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    register_both(tmp_path)

    reply = load(mailbox_mcp.do_send(BOB, ALICE, "继续刚才的任务，把剩下的部分做完并汇报进度情况"))

    assert reply["ok"] is True
    assert "线索文件路径" in reply["hint"]


def test_context_archived_not_in_wake(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    register_both(tmp_path)

    sent = load(mailbox_mcp.do_send(ALICE, BOB, "回函一句确认", context="E2E-V3 背景自述: 广播回归第 2 轮"))

    assert sent["ok"] is True
    assert "E2E-V3 背景自述" not in queued(tmp_path, BOB, sent["msg_id"])["wake_text"]
    stored = storage.read_msg(tmp_path, BOB, sent["msg_id"])
    assert stored["context"] == "E2E-V3 背景自述: 广播回归第 2 轮"


def test_expect_reply_tail_tag(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    register_both(tmp_path)

    plain = load(mailbox_mcp.do_send(ALICE, BOB, "回函一句确认"))
    tagged = load(mailbox_mcp.do_send(ALICE, BOB, "回函一句确认", expect_reply=True))

    assert plain["ok"] and "[需回函]" not in queued(tmp_path, BOB, plain["msg_id"])["wake_text"]
    assert tagged["ok"] and queued(tmp_path, BOB, tagged["msg_id"])["wake_text"].endswith("[需回函]")


def test_do_poll_and_read_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    register_both(tmp_path)
    sent = load(mailbox_mcp.do_send(ALICE, BOB, "第一行\n第二行: 读 plans/a.md"))

    polled = load(mailbox_mcp.do_poll(BOB))
    read_back = load(mailbox_mcp.do_read(BOB, sent["msg_id"]))

    assert polled["ok"] is True
    assert [item["msg_id"] for item in polled["messages"]] == [sent["msg_id"]]
    assert read_back["ok"] is True
    assert read_back["body"] == "第一行\n第二行: 读 plans/a.md"
    foreign = load(mailbox_mcp.do_read(ALICE, sent["msg_id"]))
    assert foreign["ok"] is False


def test_do_ack_requires_receiver(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    register_both(tmp_path)
    sent = load(mailbox_mcp.do_send(ALICE, BOB, "去哪读: plans/a.md"))
    sent_ack_id = queued(tmp_path, BOB, sent["msg_id"])["ack_id"]

    stolen = load(mailbox_mcp.do_ack(ALICE, sent_ack_id))
    assert stolen["ok"] is False

    proper = load(mailbox_mcp.do_ack(BOB, sent_ack_id))
    assert proper["ok"] is True
    assert proper["self_attested"] is False
    assert storage.ack_exists(tmp_path, sent_ack_id)

    again = load(mailbox_mcp.do_ack(BOB, sent_ack_id))
    assert again["ok"] is True and again["already_acked"] is True


def test_do_ack_allows_queue_owner_despite_stale_envelope_to(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    register_both(tmp_path)
    sent = load(mailbox_mcp.do_send(ALICE, BOB, "迁移滞留形态"))
    envelope = queued(tmp_path, BOB, sent["msg_id"])
    stale_ack_id = envelope["ack_id"]
    envelope["to"] = "pi-host-a-legacy-id"
    from common import atomicio

    atomicio.write_json_atomic(storage.msg_path(tmp_path, BOB, sent["msg_id"]), envelope)

    stranger = load(mailbox_mcp.do_ack(ALICE, stale_ack_id))
    assert stranger["ok"] is False

    migrated = load(mailbox_mcp.do_ack(BOB, stale_ack_id))
    assert migrated["ok"] is True
    assert not (storage.queue_dir(tmp_path, BOB) / f"{sent['msg_id']}.msg").exists()


def test_do_ack_cross_host_self_attested(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    register_both(tmp_path)

    foreign = load(mailbox_mcp.do_ack(BOB, "ack-remote-origin"))
    assert foreign["ok"] is True
    assert foreign["self_attested"] is True
    assert storage.ack_exists(tmp_path, "ack-remote-origin")


def test_do_who_reports_roster(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    register_both(tmp_path)
    storage.write_online(tmp_path, {ALICE: True, BOB: False}, 100.0)

    visible = load(mailbox_mcp.do_who(ALICE))

    assert visible["ok"] is True
    assert [item["agent_id"] for item in visible["agents"]] == [ALICE]

    roster = load(mailbox_mcp.do_who(ALICE, include_all=True))

    by_id = {item["agent_id"]: item for item in roster["agents"]}
    assert by_id[ALICE]["state"] == "active"
    assert by_id[BOB]["state"] == "stale"
    assert set(by_id[ALICE]) == {"agent_id", "display_name", "cwd", "state"}


def test_do_who_marks_stale_when_peer_down(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    register_both(tmp_path)
    CAROL = "claude-host-b-ws"
    registry.upsert(tmp_path, CAROL, {"cli": "claude", "pane_id": "%9", "pane_pid": "900", "ssh_alias": "host-b"})
    (tmp_path / "peers.json").write_text('{"peers": ["host-b"]}')
    monkeypatch.setattr(mailbox_mcp.sshio, "read_remote_json_status", lambda alias, rel: ("unreachable", None))
    storage.write_online(tmp_path, {ALICE: True, CAROL: False}, 100.0)

    visible = load(mailbox_mcp.do_who(ALICE))
    assert CAROL not in [item["agent_id"] for item in visible["agents"]]

    roster = load(mailbox_mcp.do_who(ALICE, include_all=True))

    assert roster["peers"] == [{"peer": "host-b", "ok": False, "status": "unreachable"}]
    by_id = {item["agent_id"]: item for item in roster["agents"]}
    assert by_id[CAROL]["state"] == "stale"
    assert by_id[CAROL]["peer_down"] is True
    assert by_id[ALICE].get("peer_down") is None


def test_do_who_lists_active_instance_rows(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    register_both(tmp_path)
    instances = {
        "aaaabbbb": {"session_id": "aaaabbbb-1", "pane_id": "%9", "pane_pid": "900", "slot": "s:new"},
        "olddd000": {"session_id": "olddd000-1", "pane_id": "%1", "pane_pid": "100", "slot": "s:old"},
    }
    registry.upsert(
        tmp_path, ALICE, {"cli": "claude", "pane_id": "%9", "pane_pid": "900", "instances": instances}
    )
    storage.write_online(tmp_path, {ALICE: True, BOB: True}, 100.0)

    roster = load(mailbox_mcp.do_who(BOB))

    rows = {item["agent_id"]: item for item in roster["agents"]}
    assert rows[f"{ALICE}@aaaabbbb"]["instance_of"] == ALICE
    assert rows[f"{ALICE}@aaaabbbb"]["slot"] == "s:new"
    assert rows[f"{ALICE}@aaaabbbb"]["state"] == "active"
    assert rows[f"{ALICE}@olddd000"]["pane_id"] == "%1"


def test_do_send_targets_instance_entry(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    register_both(tmp_path)
    registry.upsert(
        tmp_path,
        BOB,
        {
            "cli": "codex",
            "pane_id": "%2",
            "pane_pid": "200",
            "instances": {"aaaabbbb": {"session_id": "aaaabbbb-1", "pane_id": "%9", "pane_pid": "900"}},
        },
    )

    sent = load(mailbox_mcp.do_send(ALICE, f"{BOB}@aaaabbbb", "去哪读: plans/a.md"))

    assert sent["ok"] is True
    envelope = queued(tmp_path, BOB, sent["msg_id"])
    assert envelope["to_instance"] == "aaaabbbb"

    miss = load(mailbox_mcp.do_send(ALICE, f"{BOB}@ghost000", "去哪读: plans/a.md"))
    assert miss["ok"] is False
    assert "实例不存在" in miss["error"]
    assert "aaaabbbb" in miss["error"]


def test_split_instance_target_patterns():
    assert mailbox_mcp.split_instance_target("codex-h-2@aaaabbbb") == ("codex-h-2", "aaaabbbb")
    assert mailbox_mcp.split_instance_target("codex-h-2@%46") == ("codex-h-2", "%46")
    assert mailbox_mcp.split_instance_target("codex-h-2@Home") == ("codex-h-2@Home", "")
    assert mailbox_mcp.split_instance_target("codex-h-2") == ("codex-h-2", "")
    assert mailbox_mcp.split_instance_target("@aaaabbbb") == ("@aaaabbbb", "")


def test_respawn_offline_target_tmux_backend(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    register_both(tmp_path)
    registry.upsert(
        tmp_path, ALICE, {"cli": "claude", "pane_id": "%1", "pane_pid": "100", "slot": "s:work"}
    )
    storage.write_online(tmp_path, {ALICE: False}, 100.0)
    spawned = []
    monkeypatch.setattr(
        mailbox_mcp.tmuxio, "respawn_window", lambda slot, command: spawned.append((slot, command)) or True
    )

    hint = mailbox_mcp.respawn_offline_target(tmp_path, ALICE)

    assert spawned == [("s:work", ["claude", "-c"])]
    assert "respawn s:work" in hint
    assert "claude -c" in hint


def test_respawn_offline_target_recreates_closed_window(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    register_both(tmp_path)
    registry.upsert(
        tmp_path,
        ALICE,
        {"cli": "claude", "pane_id": "%1", "pane_pid": "100", "slot": "s:work", "cwd": "/tmp/proj"},
    )
    storage.write_online(tmp_path, {ALICE: False}, 100.0)
    monkeypatch.setattr(mailbox_mcp.tmuxio, "respawn_window", lambda slot, command: False)
    recreated = []
    monkeypatch.setattr(
        mailbox_mcp.tmuxio,
        "recreate_window",
        lambda slot, cwd, command: recreated.append((slot, cwd, command)) or True,
    )

    hint = mailbox_mcp.respawn_offline_target(tmp_path, ALICE)

    assert recreated == [("s:work", "/tmp/proj", ["claude", "-c"])]
    assert "respawn s:work" in hint


def test_respawn_offline_target_both_backends_dead(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    register_both(tmp_path)
    registry.upsert(
        tmp_path, ALICE, {"cli": "claude", "pane_id": "%1", "pane_pid": "100", "slot": "s:work"}
    )
    storage.write_online(tmp_path, {ALICE: False}, 100.0)
    monkeypatch.setattr(mailbox_mcp.tmuxio, "respawn_window", lambda slot, command: False)
    monkeypatch.setattr(mailbox_mcp.tmuxio, "recreate_window", lambda slot, cwd, command: False)

    hint = mailbox_mcp.respawn_offline_target(tmp_path, ALICE)

    assert "失败" in hint


def test_respawn_offline_target_direct_backend(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    register_both(tmp_path)
    registry.upsert(
        tmp_path, ALICE, {"cli": "pi", "pane_id": "%1", "pane_pid": "100", "slot": "s:pibox"}
    )
    storage.write_online(tmp_path, {ALICE: False}, 100.0)
    launched = []
    monkeypatch.setattr(
        mailbox_mcp.subprocess,
        "Popen",
        lambda command, **kwargs: launched.append((command, kwargs)) or object(),
    )

    hint = mailbox_mcp.respawn_offline_target(tmp_path, ALICE)

    assert launched and launched[0][0][0] in ("pi", mailbox_mcp.shutil.which("pi"))
    assert launched[0][1]["start_new_session"] is True
    assert "后台拉起" in hint


def test_respawn_offline_target_guards(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    register_both(tmp_path)
    registry.upsert(
        tmp_path,
        ALICE,
        {"cli": "claude", "pane_id": "%1", "pane_pid": "100", "slot": "", "ssh_alias": ""},
    )

    assert mailbox_mcp.respawn_offline_target(tmp_path, ALICE) == ""

    storage.write_online(tmp_path, {ALICE: False}, 100.0)
    noslot = mailbox_mcp.respawn_offline_target(tmp_path, ALICE)
    assert "无固定窗" in noslot

    storage.write_online(tmp_path, {ALICE: True}, 100.0)
    assert mailbox_mcp.respawn_offline_target(tmp_path, ALICE) == ""

    registry.upsert(
        tmp_path,
        BOB,
        {"cli": "codex", "pane_id": "%2", "pane_pid": "200", "ssh_alias": "host-b"},
    )
    storage.write_online(tmp_path, {BOB: False}, 100.0)
    assert mailbox_mcp.respawn_offline_target(tmp_path, BOB) == ""


def wire_register_env(monkeypatch, slot: str, pane_pid: str = "5000", alive: bool = False):
    monkeypatch.setattr(mailbox_mcp.detect, "current_pane_id", lambda: "%7")
    monkeypatch.setattr(mailbox_mcp.detect, "detect_cli", lambda: "claude")
    monkeypatch.setattr(mailbox_mcp.detect, "local_host", lambda: "box")
    monkeypatch.setattr(mailbox_mcp.detect, "tailscale_self_name", lambda: "")
    monkeypatch.setattr(mailbox_mcp.detect, "tailnet_host", lambda: "")
    monkeypatch.setattr(mailbox_mcp.tmuxio, "pane_slot", lambda pane, ssh=None: slot)
    monkeypatch.setattr(mailbox_mcp.tmuxio, "pane_pid", lambda pane, ssh=None: pane_pid)
    monkeypatch.setattr(mailbox_mcp.tmuxio, "pane_window_name", lambda pane, ssh=None: slot.split(":")[-1])
    monkeypatch.setattr(mailbox_mcp.tmuxio, "pane_pid_matches", lambda pane, pid, ssh=None: alive)


def test_self_register_rejects_live_agent_in_other_slot(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    (tmp_path / "proj").mkdir()
    monkeypatch.chdir(tmp_path / "proj")
    registry.upsert(
        tmp_path,
        "codex-box-proj",
        {"cli": "codex", "slot": "s:oldwin", "pane_id": "%1", "pane_pid": "100"},
    )
    wire_register_env(monkeypatch, "s:newwin", alive=True)
    monkeypatch.setattr(mailbox_mcp.detect, "detect_cli", lambda: "codex")
    monkeypatch.setattr(mailbox_mcp, "codex_anchor_fields", lambda: {})

    with pytest.raises(RuntimeError, match="异窗双开"):
        mailbox_mcp.self_register()

    registry.upsert(
        tmp_path,
        "claude-box-proj",
        {"cli": "claude", "slot": "s:oldwin", "pane_id": "%1", "pane_pid": "100"},
    )
    wire_register_env(monkeypatch, "s:newwin", alive=True)

    with pytest.raises(RuntimeError, match="异窗双开"):
        mailbox_mcp.self_register()


def test_self_register_second_window_for_multi_instance_cli(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    (tmp_path / "proj").mkdir()
    monkeypatch.chdir(tmp_path / "proj")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "aaaabbbb-1111-2222-3333-444444444444")
    registry.upsert(
        tmp_path,
        "claude-box-proj",
        {
            "cli": "claude",
            "slot": "s:oldwin",
            "pane_id": "%1",
            "pane_pid": "100",
            "instances": {
                "olddd000": {
                    "session_id": "olddd000-9999-8888-7777-666666666666",
                    "pane_id": "%1",
                    "pane_pid": "100",
                    "slot": "s:oldwin",
                }
            },
        },
    )
    wire_register_env(monkeypatch, "s:newwin", alive=True, pane_pid="5001")

    record = mailbox_mcp.self_register()

    assert record["slot"] == "s:newwin"
    assert record["pane_pid"] == "5001"
    assert set(record["instances"]) == {"olddd000", "aaaabbbb"}
    assert record["instances"]["aaaabbbb"]["slot"] == "s:newwin"
    assert record["instances"]["aaaabbbb"]["session_id"].startswith("aaaabbbb")


def test_attach_instance_entry_replaces_same_pane_session(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "newsess11-2222-3333-4444-555555555555")
    held = {
        "instances": {
            "oldsess1": {"session_id": "oldsess1-0000", "pane_id": "%7", "pane_pid": "5000", "slot": "s:w"},
            "otherpane": {"session_id": "otherpane-0000", "pane_id": "%9", "pane_pid": "9000", "slot": "s:x"},
        },
        "fingerprint": "conv-keep",
    }

    record = mailbox_mcp.attach_instance_entry(dict(held), held, "claude", "%7", "5000", "s:w")

    assert set(record["instances"]) == {"otherpane", "newsess1"}
    assert record["instances"]["newsess1"]["fingerprint"] == "conv-keep"


def test_self_register_continues_dead_agent_preserving_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    (tmp_path / "proj").mkdir()
    monkeypatch.chdir(tmp_path / "proj")
    registry.upsert(
        tmp_path,
        "claude-box-proj",
        {
            "cli": "claude",
            "slot": "s:oldwin",
            "pane_id": "%1",
            "pane_pid": "100",
            "fingerprint": "conv-keep123",
            "started_at": 42.0,
            "spawn_cmd": ["z"],
            "ssh_alias": "host-b",
        },
    )
    wire_register_env(monkeypatch, "s:newwin", alive=False)

    record = mailbox_mcp.self_register()

    assert record["slot"] == "s:newwin"
    assert record["fingerprint"] == "conv-keep123"
    assert record["started_at"] == 42.0
    assert record["spawn_cmd"] == ["z"]
    assert record["ssh_alias"] == "host-b"


def test_self_register_fingerprint_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    (tmp_path / "proj").mkdir()
    monkeypatch.chdir(tmp_path / "proj")
    monkeypatch.setenv("A2A_FINGERPRINT", "conv-fromenv7")
    wire_register_env(monkeypatch, "s:fresh")

    record = mailbox_mcp.self_register()

    assert record["fingerprint"] == "conv-fromenv7"


class BootRecorder:
    def __init__(self):
        self.commands = []

    def __call__(self, command, **kwargs):
        self.commands.append((command, kwargs))
        proc = type("Proc", (), {"poll": staticmethod(lambda: 0)})()
        return proc


def test_boot_hub_if_absent_spawns_when_unlocked(tmp_path, monkeypatch):
    spawner = BootRecorder()
    monkeypatch.setattr(mailbox_mcp.subprocess, "Popen", spawner)
    monkeypatch.setattr(mailbox_mcp, "hub_boot_command", lambda: ["python3", "hub/hub.py"])

    REAL_BOOT_HUB(tmp_path)

    assert len(spawner.commands) == 1
    assert spawner.commands[0][1]["start_new_session"] is True


def test_boot_hub_if_absent_skips_when_lock_held(tmp_path, monkeypatch):
    import fcntl

    spawner = BootRecorder()
    monkeypatch.setattr(mailbox_mcp.subprocess, "Popen", spawner)
    holder = open(tmp_path / "hub.lock", "w")
    try:
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        REAL_BOOT_HUB(tmp_path)
        assert spawner.commands == []
    finally:
        holder.close()


def test_hub_boot_command_rejects_exe(monkeypatch):
    monkeypatch.setenv("A2A_HUB_CMD", "C:/tool/agent.exe --boot")
    assert mailbox_mcp.hub_boot_command() is None
    monkeypatch.setenv("A2A_HUB_CMD", 'bash -c "hub"')
    assert mailbox_mcp.hub_boot_command() == ["bash", "-c", "hub"]


def test_register_failure_surfaces_reason_and_retry_heals(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    register_both(tmp_path)
    monkeypatch.setattr(mailbox_mcp, "SELF", {})
    monkeypatch.setattr(mailbox_mcp.tmuxio, "pane_pid_matches", lambda pane, pid, ssh=None: False)

    def blocked_register():
        raise RuntimeError("slot pi:claude 已有活跃对话(pi-agent), 同 tmux 名禁止双开——换窗名再启动")

    monkeypatch.setattr(mailbox_mcp, "self_register", blocked_register)
    blocked = load(mailbox_mcp.mail_who())
    assert blocked["ok"] is False
    assert "已有活跃对话" in blocked["error"]
    assert "换 tmux 窗名" in blocked["error"]

    healed = {"agent_id": ALICE, "pane_id": "%1"}
    monkeypatch.setattr(mailbox_mcp, "self_register", lambda: healed)
    verdict = load(mailbox_mcp.mail_who())
    assert verdict["ok"] is True
    assert mailbox_mcp.SELF is healed


def test_do_send_distinguishes_peer_unreachable(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    register_both(tmp_path)
    (tmp_path / "peers.json").write_text('{"peers": ["host-b"]}')
    calls = {"count": 0}

    def unreachable_read(alias, rel):
        calls["count"] += 1
        return ("unreachable", None)

    monkeypatch.setattr(mailbox_mcp.sshio, "read_remote_json_status", unreachable_read)
    mailbox_mcp.PEER_UNREACHABLE_CACHE.clear()

    first = load(mailbox_mcp.do_send(BOB, ALICE, "去哪读: plans/b.md", in_reply_to="m-gone-1"))
    assert first["ok"] is False
    assert "不可达" in first["error"]
    assert "不存在" not in first["error"]

    second = load(mailbox_mcp.do_send(BOB, ALICE, "去哪读: plans/b.md", in_reply_to="m-gone-2"))
    assert second["ok"] is False
    assert "不可达" in second["error"]
    assert calls["count"] == 1


def test_do_read_payload_is_lean_with_ack_id(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    register_both(tmp_path)
    first = load(mailbox_mcp.do_send(ALICE, BOB, "去哪读: plans/a.md", context="背景X"))
    tagged = load(mailbox_mcp.do_send(BOB, ALICE, "回函: 读完了", in_reply_to=first["msg_id"], expect_reply=True))

    plain_read = load(mailbox_mcp.do_read(BOB, first["msg_id"]))
    tagged_read = load(mailbox_mcp.do_read(ALICE, tagged["msg_id"]))

    assert plain_read["ack_id"] and plain_read["ack_id"].startswith("ack-")
    assert plain_read["body"] == "去哪读: plans/a.md"
    assert plain_read["context"] == "背景X"
    assert "wake_text" not in plain_read and "created_at" not in plain_read and "hop" not in plain_read
    assert "expect_reply" not in plain_read
    assert tagged_read["expect_reply"] is True
    assert tagged_read["in_reply_to"] == first["msg_id"]

    polled = load(mailbox_mcp.do_poll(ALICE))["messages"]
    assert polled and polled[0]["in_reply_to"] == first["msg_id"] and polled[0]["hop"] == 2
    fresh = load(mailbox_mcp.do_send(ALICE, BOB, "回函: 新腿OK"))
    polled_bob = load(mailbox_mcp.do_poll(BOB))["messages"]
    entry = next(item for item in polled_bob if item["msg_id"] == fresh["msg_id"])
    assert "in_reply_to" not in entry and "hop" not in entry


def seed_pi_held(tmp_path, monkeypatch, pane_env, held_extra=None):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    monkeypatch.setattr(mailbox_mcp.paths, "mailbox_root", lambda: tmp_path)
    monkeypatch.setenv("TMUX_PANE", pane_env) if pane_env else monkeypatch.delenv("TMUX_PANE", raising=False)
    monkeypatch.setattr(mailbox_mcp.detect, "detect_cli", lambda: "pi")
    monkeypatch.setattr(mailbox_mcp.detect, "current_pane_id", lambda: pane_env or "")
    monkeypatch.setattr(mailbox_mcp.detect, "local_host", lambda: "host-a")
    monkeypatch.setattr(mailbox_mcp.detect, "tailnet_host", lambda: "")
    monkeypatch.setattr(mailbox_mcp, "spawn_cmd_from_env", lambda: None)
    monkeypatch.setattr(mailbox_mcp, "ssh_alias_from_env", lambda: "")
    monkeypatch.setattr(mailbox_mcp.tmuxio, "pane_slot", lambda pane, ssh=None: "pi:pi-live" if pane else "")
    monkeypatch.setattr(mailbox_mcp.tmuxio, "pane_pid", lambda pane, ssh=None: "2010894" if pane else "")
    monkeypatch.setattr(mailbox_mcp.tmuxio, "pane_window_name", lambda pane, ssh=None: "pi-live" if pane else "")
    monkeypatch.setattr(mailbox_mcp.tmuxio, "pane_pid_matches", lambda pane, pid, ssh=None: bool(pane) and pid == "2010894")
    agent_id = mailbox_mcp.detect.build_agent_id("pi", os.getcwd())
    held = {"agent_id": agent_id, "cli": "pi", "cwd": os.getcwd(), "pane_id": "", "ssh_alias": "host-b"}
    held.update(held_extra or {})
    registry.upsert(tmp_path, agent_id, held)
    return agent_id


def test_local_pane_registration_drops_stale_ssh_alias(tmp_path, monkeypatch):
    agent_id = seed_pi_held(tmp_path, monkeypatch, "%49")
    record = mailbox_mcp.register_record()
    assert record["pane_id"] == "%49"
    assert record["ssh_alias"] == ""


def test_bridge_registration_keeps_held_ssh_alias(tmp_path, monkeypatch):
    agent_id = seed_pi_held(tmp_path, monkeypatch, "")
    record = mailbox_mcp.register_record()
    assert record["pane_id"] == ""
    assert record["ssh_alias"] == "host-b"


def test_slot_reuse_refreshes_ssh_alias_from_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    agent_id = seed_pi_held(tmp_path, monkeypatch, "%49", held_extra={"slot": "pi:pi-live", "pane_id": "%49", "pane_pid": "2010894"})
    record = mailbox_mcp.register_record()
    assert record["agent_id"] == agent_id
    assert record["pane_id"] == "%49"
    assert record["ssh_alias"] == ""


def test_ack_archives_message_for_pull_recipient(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    envelope = {
        "msg_id": "pk0001",
        "ack_id": "ack-pk0001",
        "from": ALICE,
        "to": BOB,
        "body": "拉取型读侧归档",
        "created_at": 1.0,
        "wake_text": "[A2A] from=claude-h-1 id=pk0001\n拉取型读侧归档",
    }
    storage.enqueue(tmp_path, envelope)
    mailbox_mcp.do_ack(BOB, "ack-pk0001")
    assert storage.read_msg(tmp_path, BOB, "pk0001") is None
    assert (tmp_path / "history" / "pk0001.json").exists()
    result = load(mailbox_mcp.do_ack(BOB, "ack-pk0001"))
    assert result["already_acked"] is True


def test_codex_registration_anchors_queue_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    monkeypatch.setattr(mailbox_mcp.paths, "mailbox_root", lambda: tmp_path)
    monkeypatch.setattr(mailbox_mcp.detect, "detect_cli", lambda: "codex")
    monkeypatch.setattr(mailbox_mcp.detect, "current_pane_id", lambda: "%17")
    monkeypatch.setattr(mailbox_mcp.detect, "local_host", lambda: "host-a")
    monkeypatch.setattr(mailbox_mcp.detect, "tailnet_host", lambda: "")
    monkeypatch.setattr(mailbox_mcp, "spawn_cmd_from_env", lambda: None)
    monkeypatch.setattr(mailbox_mcp, "ssh_alias_from_env", lambda: "")
    monkeypatch.setattr(mailbox_mcp, "codex_anchor_fields", lambda: {
        "codex_bin": "/usr/local/bin/codex",
        "codex_home": "/home/u/.codex",
        "codex_thread": "aaaa5c8b-07a4-7f61-a73c-312c7a2d915e",
    })
    monkeypatch.setattr(mailbox_mcp.tmuxio, "pane_slot", lambda pane, ssh=None: "w:codex")
    monkeypatch.setattr(mailbox_mcp.tmuxio, "pane_pid", lambda pane, ssh=None: "700")
    monkeypatch.setattr(mailbox_mcp.tmuxio, "pane_window_name", lambda pane, ssh=None: "codex")
    record = mailbox_mcp.register_record()
    assert record["codex_bin"] == "/usr/local/bin/codex"
    assert record["codex_home"] == "/home/u/.codex"
    assert record["codex_thread"] == "aaaa5c8b-07a4-7f61-a73c-312c7a2d915e"


def test_do_send_relays_queue_anchor_recipient_to_home_hub(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    register_both(tmp_path)
    record = dict(registry.get(tmp_path, BOB))
    record.update(
        {
            "pane_id": "",
            "pane_pid": "",
            "spawn_cmd": None,
            "ssh_alias": "host-b",
            "codex_bin": "/mnt/c/codex.exe",
            "codex_home": "/mnt/c/.codex",
            "codex_thread": "aaaa5c8b-07a4-7f61-a73c-312c7a2d915e",
        }
    )
    registry.upsert(tmp_path, BOB, record)
    relayed = {}

    def fake_write(alias, envelope):
        relayed["alias"] = alias
        relayed["envelope"] = envelope
        return "ok"

    monkeypatch.setattr(mailbox_mcp.sshio, "write_remote_envelope", fake_write)
    result = load(mailbox_mcp.do_send(ALICE, BOB, "远端直投: 读 plans/next.md 后继续"))
    assert result["relayed_to"] == "host-b"
    assert relayed["alias"] == "host-b"
    assert relayed["envelope"]["to"] == BOB
    assert storage.read_msg(tmp_path, BOB, result["msg_id"]) is None


def test_do_send_falls_back_local_when_relay_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    register_both(tmp_path)
    record = dict(registry.get(tmp_path, BOB))
    record.update(
        {
            "pane_id": "",
            "pane_pid": "",
            "spawn_cmd": None,
            "ssh_alias": "host-b",
            "codex_bin": "/mnt/c/codex.exe",
            "codex_home": "/mnt/c/.codex",
            "codex_thread": "aaaa5c8b-07a4-7f61-a73c-312c7a2d915e",
        }
    )
    registry.upsert(tmp_path, BOB, record)
    monkeypatch.setattr(mailbox_mcp.sshio, "write_remote_envelope", lambda alias, envelope: "unreachable")
    result = load(mailbox_mcp.do_send(ALICE, BOB, "回落本机: 读 plans/next.md 后继续"))
    assert "relayed_to" not in result
    assert "回落本机队列" in result["hint"]
    assert storage.read_msg(tmp_path, BOB, result["msg_id"]) is not None


def test_held_codex_anchor_survives_re_registration(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    monkeypatch.setattr(mailbox_mcp.paths, "mailbox_root", lambda: tmp_path)
    monkeypatch.setattr(mailbox_mcp.detect, "detect_cli", lambda: "codex")
    monkeypatch.setattr(mailbox_mcp.detect, "current_pane_id", lambda: "")
    monkeypatch.setattr(mailbox_mcp.detect, "local_host", lambda: "host-a")
    monkeypatch.setattr(mailbox_mcp.detect, "tailnet_host", lambda: "")
    monkeypatch.setattr(mailbox_mcp, "spawn_cmd_from_env", lambda: None)
    monkeypatch.setattr(mailbox_mcp, "ssh_alias_from_env", lambda: "")
    monkeypatch.setattr(mailbox_mcp, "codex_anchor_fields", lambda: {})
    monkeypatch.setattr(mailbox_mcp.tmuxio, "pane_slot", lambda pane, ssh=None: "")
    monkeypatch.setattr(mailbox_mcp.tmuxio, "pane_pid", lambda pane, ssh=None: "")
    monkeypatch.setattr(mailbox_mcp.tmuxio, "pane_window_name", lambda pane, ssh=None: "")
    mailbox_mcp.register_record()
    agent_id = mailbox_mcp.detect.build_agent_id("codex", os.getcwd())
    registry.upsert(tmp_path, agent_id, registry.get(tmp_path, agent_id))
    held = registry.get(tmp_path, agent_id)
    held.update(
        {
            "codex_bin": "/mnt/c/codex.exe",
            "codex_home": "/mnt/c/.codex",
            "codex_thread": "aaaa5c8b-07a4-7f61-a73c-312c7a2d915e",
        }
    )
    registry.upsert(tmp_path, agent_id, held)
    fresh = mailbox_mcp.register_record()
    assert fresh["codex_bin"] == "/mnt/c/codex.exe"
    assert fresh["codex_thread"] == "aaaa5c8b-07a4-7f61-a73c-312c7a2d915e"


def test_win_bridge_registration_anchors_without_ssh_alias(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    monkeypatch.setenv("A2A_SSH_ALIAS", "host-b")
    monkeypatch.setattr(mailbox_mcp.paths, "mailbox_root", lambda: tmp_path)
    monkeypatch.setattr(mailbox_mcp.detect, "detect_cli", lambda: "codex")
    monkeypatch.setattr(mailbox_mcp.detect, "current_pane_id", lambda: "")
    monkeypatch.setattr(mailbox_mcp.detect, "local_host", lambda: "host-b")
    monkeypatch.setattr(mailbox_mcp.detect, "tailnet_host", lambda: "")
    monkeypatch.setattr(mailbox_mcp, "spawn_cmd_from_env", lambda: None)
    monkeypatch.setattr(mailbox_mcp, "shutil", type("S", (), {"which": staticmethod(lambda name: None)}))
    monkeypatch.setattr(mailbox_mcp.codexq, "thread_from_ancestors", lambda: "")
    monkeypatch.setattr(
        mailbox_mcp.codexq,
        "locate_win",
        lambda cwd: {
            "codex_bin": "/mnt/c/Users/winuser/AppData/Local/OpenAI/Codex/bin/abc/codex.exe",
            "codex_home": "/mnt/c/Users/winuser/.codex",
            "codex_thread": "bbbb07cd-216d-7891-a859-cde40971c5aa",
        },
    )
    monkeypatch.setattr(mailbox_mcp.tmuxio, "pane_slot", lambda pane, ssh=None: "")
    monkeypatch.setattr(mailbox_mcp.tmuxio, "pane_pid", lambda pane, ssh=None: "")
    monkeypatch.setattr(mailbox_mcp.tmuxio, "pane_window_name", lambda pane, ssh=None: "")
    record = mailbox_mcp.register_record()
    assert record["codex_thread"] == "bbbb07cd-216d-7891-a859-cde40971c5aa"
    assert record["codex_home"] == "/mnt/c/Users/winuser/.codex"
    assert record["ssh_alias"] == ""


def patch_registration_identity(monkeypatch, tmp_path, cli="unknown", build="unknown-host-b-000-host-c"):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    monkeypatch.delenv("A2A_AGENT_ID", raising=False)
    monkeypatch.setattr(mailbox_mcp.paths, "mailbox_root", lambda: tmp_path)
    monkeypatch.setattr(mailbox_mcp.detect, "detect_cli", lambda: cli)
    monkeypatch.setattr(mailbox_mcp.os, "getcwd", lambda: "/mnt/d/000-project")
    monkeypatch.setattr(mailbox_mcp.detect, "current_pane_id", lambda: "")
    monkeypatch.setattr(mailbox_mcp.detect, "local_host", lambda: "localhost")
    monkeypatch.setattr(mailbox_mcp.detect, "tailnet_host", lambda: "")
    monkeypatch.setattr(mailbox_mcp, "spawn_cmd_from_env", lambda: None)
    monkeypatch.setattr(mailbox_mcp, "shutil", type("S", (), {"which": staticmethod(lambda name: None)}))
    monkeypatch.setattr(mailbox_mcp.codexq, "thread_from_ancestors", lambda: "")
    monkeypatch.setattr(mailbox_mcp.codexq, "locate_win", lambda cwd: {})
    monkeypatch.setattr(mailbox_mcp.tmuxio, "pane_slot", lambda pane, ssh=None: "")
    monkeypatch.setattr(mailbox_mcp.tmuxio, "pane_pid", lambda pane, ssh=None: "")
    monkeypatch.setattr(mailbox_mcp.tmuxio, "pane_window_name", lambda pane, ssh=None: "")
    monkeypatch.setattr(mailbox_mcp.detect, "build_agent_id", lambda cli, cwd: build)


def anchored_twin_record(agent_id, cwd="/mnt/d/000-project"):
    return {
        "agent_id": agent_id,
        "cli": "codex",
        "host": "localhost",
        "cwd": cwd,
        "pane_id": "",
        "pane_pid": "",
        "slot": "",
        "codex_bin": "/mnt/c/Users/winuser/AppData/Local/OpenAI/Codex/bin/abc/codex.exe",
        "codex_home": "/mnt/c/Users/winuser/.codex",
        "codex_thread": "01a15887-ec89-7df1-99aa-50888f2246a9",
        "ssh_alias": "",
    }


def test_register_collapses_detect_swing_into_anchored_identity(tmp_path, monkeypatch):
    patch_registration_identity(monkeypatch, tmp_path, cli="unknown", build="unknown-host-b-000-host-c")
    registry.upsert(tmp_path, "codex-host-b-000-host-c", anchored_twin_record("codex-host-b-000-host-c"))
    record = mailbox_mcp.register_record()
    assert record["agent_id"] == "codex-host-b-000-host-c"
    assert record["codex_home"] == "/mnt/c/Users/winuser/.codex"
    assert record["codex_thread"] == "01a15887-ec89-7df1-99aa-50888f2246a9"
    agents = registry.load(tmp_path)["agents"]
    assert "unknown-host-b-000-host-c" not in agents


def test_register_ambiguous_anchor_twins_stay_split(tmp_path, monkeypatch):
    patch_registration_identity(monkeypatch, tmp_path, cli="unknown", build="unknown-host-b-000-host-c")
    registry.upsert(tmp_path, "codex-host-b-000-host-c", anchored_twin_record("codex-host-b-000-host-c"))
    registry.upsert(tmp_path, "codex-host-b-000-other", anchored_twin_record("codex-host-b-000-other"))
    record = mailbox_mcp.register_record()
    assert record["agent_id"] == "unknown-host-b-000-host-c"
    assert len(registry.load(tmp_path)["agents"]) == 3


def test_register_explicit_env_beats_anchor_inheritance(tmp_path, monkeypatch):
    patch_registration_identity(monkeypatch, tmp_path, cli="unknown", build="unknown-host-b-000-host-c")
    monkeypatch.setenv("A2A_AGENT_ID", "codex-main-host-b-host-c")
    monkeypatch.setattr(
        mailbox_mcp.detect,
        "build_agent_id",
        lambda cli, cwd: "codex-main-host-b-host-c",
    )
    registry.upsert(tmp_path, "codex-host-b-000-host-c", anchored_twin_record("codex-host-b-000-host-c"))
    record = mailbox_mcp.register_record()
    assert record["agent_id"] == "codex-main-host-b-host-c"


def test_held_anchor_reconnect_never_reclaims_ssh_alias(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    monkeypatch.setenv("A2A_SSH_ALIAS", "host-b")
    monkeypatch.setattr(mailbox_mcp.paths, "mailbox_root", lambda: tmp_path)
    monkeypatch.setattr(mailbox_mcp.detect, "detect_cli", lambda: "unknown")
    monkeypatch.setattr(mailbox_mcp.detect, "current_pane_id", lambda: "")
    monkeypatch.setattr(mailbox_mcp.detect, "local_host", lambda: "localhost")
    monkeypatch.setattr(mailbox_mcp.detect, "tailnet_host", lambda: "")
    monkeypatch.setattr(mailbox_mcp, "spawn_cmd_from_env", lambda: None)
    monkeypatch.setattr(mailbox_mcp, "shutil", type("S", (), {"which": staticmethod(lambda name: None)}))
    monkeypatch.setattr(mailbox_mcp.codexq, "thread_from_ancestors", lambda: "")
    monkeypatch.setattr(mailbox_mcp.codexq, "locate_win", lambda cwd: {})
    monkeypatch.setattr(mailbox_mcp.tmuxio, "pane_slot", lambda pane, ssh=None: "")
    monkeypatch.setattr(mailbox_mcp.tmuxio, "pane_pid", lambda pane, ssh=None: "")
    monkeypatch.setattr(mailbox_mcp.tmuxio, "pane_window_name", lambda pane, ssh=None: "")
    registry.upsert(
        tmp_path,
        "unknown-host-b-000-host-c",
        {
            "agent_id": "unknown-host-b-000-host-c",
            "cli": "unknown",
            "host": "localhost",
            "cwd": "/mnt/d/000-project",
            "pane_id": "",
            "pane_pid": "",
            "slot": "",
            "codex_bin": "/mnt/c/Users/winuser/AppData/Local/OpenAI/Codex/bin/abc/codex.exe",
            "codex_home": "/mnt/c/Users/winuser/.codex",
            "codex_thread": "bbbb07cd-216d-7891-a859-cde40971c5aa",
            "ssh_alias": "",
        },
    )
    monkeypatch.setattr(mailbox_mcp.detect, "build_agent_id", lambda cli, cwd: "unknown-host-b-000-host-c")
    reconnected = mailbox_mcp.register_record()
    assert reconnected["codex_thread"] == "bbbb07cd-216d-7891-a859-cde40971c5aa"
    assert reconnected["ssh_alias"] == ""


def test_do_send_stamps_schema_version(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    register_both(tmp_path)

    sent = load(mailbox_mcp.do_send(ALICE, BOB, "去哪读: plans/a.md"))

    envelope = queued(tmp_path, BOB, sent["msg_id"])
    assert envelope["schema_version"] == 1


def test_slot_claim_rejected_on_cwd_mismatch(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    (tmp_path / "fe").mkdir()
    (tmp_path / "be").mkdir()
    registry.upsert(
        tmp_path,
        "claude-box-fe",
        {"cli": "claude", "slot": "s:frontend", "pane_id": "%11", "pane_pid": "390988", "cwd": str(tmp_path / "fe")},
    )
    monkeypatch.chdir(tmp_path / "be")
    wire_register_env(monkeypatch, "s:frontend", alive=False, pane_pid="389427")
    monkeypatch.setattr(mailbox_mcp, "codex_anchor_fields", lambda: {})

    record = mailbox_mcp.self_register()

    assert record["agent_id"] == "claude-box-be"
    held = registry.get(tmp_path, "claude-box-fe")
    assert held["pane_id"] == "%11"
    assert held["cwd"] == str(tmp_path / "fe")


def test_session_proof_adopts_across_window_move(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess1234-9999-8888-7777-666666666666")
    (tmp_path / "proj").mkdir()
    monkeypatch.chdir(tmp_path / "proj")
    registry.upsert(
        tmp_path,
        "claude-box-proj",
        {
            "cli": "claude",
            "slot": "s:oldwin",
            "pane_id": "%1",
            "pane_pid": "100",
            "cwd": str(tmp_path / "proj"),
            "instances": {
                "sess1234": {
                    "session_id": "sess1234-9999-8888-7777-666666666666",
                    "pane_id": "%1",
                    "pane_pid": "100",
                    "slot": "s:oldwin",
                }
            },
        },
    )
    wire_register_env(monkeypatch, "s:newwin", alive=False, pane_pid="5001")
    monkeypatch.setattr(mailbox_mcp, "codex_anchor_fields", lambda: {})

    record = mailbox_mcp.self_register()

    assert record["agent_id"] == "claude-box-proj"
    assert record["slot"] == "s:newwin"
    assert record["pane_pid"] == "5001"
    assert record["instances"]["sess1234"]["slot"] == "s:newwin"
