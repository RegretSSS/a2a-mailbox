import importlib.util
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import paths, registry, storage

import importlib

_hub_spec = importlib.util.spec_from_file_location(
    "hub_group_gate", Path(__file__).resolve().parent.parent / "hub" / "hub.py"
)
hubd = importlib.util.module_from_spec(_hub_spec)
_hub_spec.loader.exec_module(hubd)

_spec = importlib.util.spec_from_file_location(
    "mailbox_mcp_group", Path(__file__).resolve().parent.parent / "mcp" / "mailbox_mcp.py"
)
mailbox_mcp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mailbox_mcp)

ALICE = "claude-h-1"
BOB = "codex-h-2"
MAIN = "claude-h-3"
CAROL = "pi-h-4"


def load(text: str) -> dict:
    return json.loads(text)


def register_all(tmp_path):
    for agent_id, pane_pid in ((ALICE, "100"), (BOB, "200"), (MAIN, "300"), (CAROL, "400")):
        registry.upsert(tmp_path, agent_id, {"cli": agent_id.split("-")[0], "pane_id": f"%{pane_pid}", "pane_pid": pane_pid})


def test_subagent_scope_locks_send_to_main(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    register_all(tmp_path)
    registry.upsert(tmp_path, BOB, {"cli": "codex", "pane_id": "%2", "pane_pid": "200", "peer_of": MAIN})

    denied = load(mailbox_mcp.do_send(BOB, ALICE, "查: 任意目标"))
    assert denied["ok"] is False and "subagent 发送锁" in denied["error"]

    allowed = load(mailbox_mcp.do_send(BOB, MAIN, "回: 主 agent 结果"))
    assert allowed["ok"] is True


def test_group_only_gate_admit_revoke_cycle(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    register_all(tmp_path)
    gated = load(mailbox_mcp.do_group_gate(BOB, True, "host-c"))
    assert gated["ok"] is True and gated["group_only"] is True

    denied = load(mailbox_mcp.do_send(ALICE, BOB, "查: 未准入直发"))
    assert denied["ok"] is False and "group-only" in denied["error"] and "mail_group(action=join" in denied["error"]

    admitted = load(mailbox_mcp.do_admit(BOB, ALICE))
    assert admitted["ok"] is True
    allowed = load(mailbox_mcp.do_send(ALICE, BOB, "查: 准入后直发"))
    assert allowed["ok"] is True

    revoked = load(mailbox_mcp.do_revoke(BOB, ALICE))
    assert revoked["ok"] is True
    denied_again = load(mailbox_mcp.do_send(ALICE, BOB, "查: 除名后直发"))
    assert denied_again["ok"] is False


def test_join_request_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    register_all(tmp_path)
    mailbox_mcp.do_group_gate(BOB, True, "host-c")

    requested = load(mailbox_mcp.do_request_join(CAROL, BOB, "加入协作批B"))
    assert requested["ok"] is True
    pending = load(mailbox_mcp.do_pending_joins(BOB))["requests"]
    assert [item["from"] for item in pending] == [CAROL]
    assert pending[0]["note"] == "加入协作批B"

    admitted = load(mailbox_mcp.do_admit(BOB, CAROL))
    assert admitted["ok"] is True
    assert load(mailbox_mcp.do_pending_joins(BOB))["requests"] == []
    assert load(mailbox_mcp.do_send(CAROL, BOB, "查: 通过申请后直发"))["ok"] is True

    again = load(mailbox_mcp.do_request_join(CAROL, BOB, "再次申请"))
    assert again["ok"] is True and again.get("already_admitted") is True


def test_join_request_relays_to_remote_gatekeeper(tmp_path, monkeypatch):
    from common import sshio

    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    register_all(tmp_path)
    remote = registry.load(tmp_path)["agents"][BOB]
    remote["ssh_alias"] = "node-9"
    registry.upsert(tmp_path, BOB, remote)
    relayed = []

    def fake_write(alias, to, sender, payload):
        relayed.append((alias, to, sender, payload["note"]))
        return sshio.REMOTE_OK

    monkeypatch.setattr(mailbox_mcp.sshio, "write_remote_join", fake_write)
    sent = load(mailbox_mcp.do_request_join(CAROL, BOB, "跨机申请"))
    assert sent["ok"] is True and sent["relayed_to"] == "node-9"
    assert relayed == [("node-9", BOB, CAROL, "跨机申请")]
    assert not (tmp_path / "join-requests" / BOB).exists()

    monkeypatch.setattr(mailbox_mcp.sshio, "write_remote_join", lambda *a: sshio.REMOTE_UNREACHABLE)
    failed = load(mailbox_mcp.do_request_join(MAIN, BOB, "跨机申请二"))
    assert failed["ok"] is False and "node-9" in failed["error"]


def test_who_shows_group_markers_without_full_roster(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    register_all(tmp_path)
    monkeypatch.setattr(mailbox_mcp.federation, "pull_all", lambda root: [])
    mailbox_mcp.do_group_gate(BOB, True, "host-c")
    mailbox_mcp.do_admit(BOB, ALICE)
    registry.upsert(tmp_path, CAROL, {"cli": "pi", "pane_id": "%4", "pane_pid": "400", "peer_of": MAIN})

    payload = load(mailbox_mcp.do_who(ALICE))
    by_id = {entry["agent_id"]: entry for entry in payload["agents"]}
    assert by_id[BOB]["group"] == "host-c" and by_id[BOB]["group_only"] is True
    assert by_id[BOB]["members"] == 1 and "allowed_senders" not in by_id[BOB]
    assert by_id[CAROL]["subagent_of"] == MAIN

    self_view = load(mailbox_mcp.do_who(BOB))
    own = {entry["agent_id"]: entry for entry in self_view["agents"]}[BOB]
    assert own["allowed_senders"] == [ALICE]


def envelope_to_gated(msg_id, sender):
    wake = mailbox_mcp.msgfmt.compose_wake(sender, msg_id, "绕过 MCP 直写", False)
    return {
        "msg_id": msg_id,
        "ack_id": f"ack-{msg_id}",
        "from": sender,
        "to": BOB,
        "body": "绕过 MCP 直写",
        "created_at": time.time(),
        "expect_reply": False,
        "wake_text": wake,
    }


def test_hub_rejects_unadmitted_and_scope_violations(tmp_path):
    paths.ensure_layout(tmp_path)
    register_all(tmp_path)
    record = registry.load(tmp_path)["agents"][BOB]
    record["group_only"] = True
    record["allowed_senders"] = [ALICE]
    registry.upsert(tmp_path, BOB, record)
    storage.enqueue(tmp_path, envelope_to_gated("gg0000000001", MAIN))
    storage.enqueue(tmp_path, envelope_to_gated("gg0000000002", ALICE))
    sender = registry.load(tmp_path)["agents"][CAROL]
    sender["peer_of"] = MAIN
    registry.upsert(tmp_path, CAROL, sender)
    storage.enqueue(tmp_path, envelope_to_gated("gg0000000003", CAROL))

    reg = registry.load(tmp_path)
    deliveries: dict = {}
    log = FakeLog()
    hubd.step(tmp_path, reg, deliveries, log, time.time(), {BOB: True})

    assert (tmp_path / "queue" / BOB / "gg0000000001.failed").exists()
    assert storage.read_msg(tmp_path, BOB, "gg0000000002") is not None
    assert (tmp_path / "queue" / BOB / "gg0000000003.failed").exists()
    assert any("group-reject" in line for line in log.lines)
    assert any("scope-reject" in line for line in log.lines)
    assert len(list((tmp_path / "queue" / MAIN).glob("*.msg"))) == 1
    assert len(list((tmp_path / "queue" / CAROL).glob("*.msg"))) == 1


def test_group_dispatcher_routes_all_actions(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    register_all(tmp_path)

    joined = load(mailbox_mcp.do_group(CAROL, "join", agent_id=BOB, note="调度器申请"))
    assert joined["ok"] is True
    assert (tmp_path / "join-requests" / BOB / f"{CAROL}.json").exists()

    pending = load(mailbox_mcp.do_group(BOB, "pending"))
    assert [item["from"] for item in pending["requests"]] == [CAROL]
    assert pending["requests"][0]["note"] == "调度器申请"

    admitted = load(mailbox_mcp.do_group(BOB, "admit", agent_id=CAROL))
    assert admitted["ok"] is True and admitted["members"] == 1
    assert load(mailbox_mcp.do_send(CAROL, BOB, "查: 调度器准入后直发"))["ok"] is True

    gated = load(mailbox_mcp.do_group(BOB, "gate", group_only=True, group="dispatch"))
    assert gated["ok"] is True and gated["group_only"] is True and gated["group"] == "dispatch"

    revoked = load(mailbox_mcp.do_group(BOB, "revoke", agent_id=CAROL))
    assert revoked["ok"] is True and revoked["members"] == 0
    assert load(mailbox_mcp.do_send(CAROL, BOB, "查: 调度器除名后直发"))["ok"] is False

    upper = load(mailbox_mcp.do_group(BOB, "PENDING"))
    assert upper["ok"] is True and upper["requests"] == []


def test_group_dispatcher_rejects_unknown_and_missing_args(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    register_all(tmp_path)

    unknown = load(mailbox_mcp.do_group(ALICE, "invite"))
    assert unknown["ok"] is False and "action=join" in unknown["error"] and "action=gate" in unknown["error"]

    missing = load(mailbox_mcp.do_group(ALICE, "admit"))
    assert missing["ok"] is False and "action=admit" in missing["error"]

    joinless = load(mailbox_mcp.do_group(ALICE, "join"))
    assert joinless["ok"] is False and "agent_id" in joinless["error"]

    assert not (tmp_path / "join-requests").exists()


def test_hub_leaves_injected_mail_out_of_gates(tmp_path):
    paths.ensure_layout(tmp_path)
    register_all(tmp_path)
    record = registry.load(tmp_path)["agents"][BOB]
    record["group_only"] = True
    record["allowed_senders"] = []
    registry.upsert(tmp_path, BOB, record)
    injected = envelope_to_gated("gg0000000004", MAIN)
    injected["last_injected_at"] = time.time() - 120
    storage.enqueue(tmp_path, injected)

    reg = registry.load(tmp_path)
    deliveries: dict = {}
    log = FakeLog()
    hubd.step(tmp_path, reg, deliveries, log, time.time(), {BOB: True})

    assert storage.read_msg(tmp_path, BOB, "gg0000000004") is not None
    assert not (tmp_path / "queue" / BOB / "gg0000000004.failed").exists()
    assert not any("group-reject" in line for line in log.lines)
    assert f"{BOB}/gg0000000004" in deliveries
    assert len(list((tmp_path / "queue" / MAIN).glob("*.msg"))) == 0


class FakeLog:
    def __init__(self):
        self.lines = []

    def write(self, line):
        self.lines.append(line)
