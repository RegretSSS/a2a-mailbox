import importlib.util
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import msgfmt, paths, registry, storage
from hub.hub import INPUT_ZONE_LINES

_SPEC = importlib.util.spec_from_file_location(
    "hubd", Path(__file__).resolve().parent.parent / "hub" / "hub.py"
)
hubd = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hubd)

REAL_LOAD_NOTIFY = hubd.load_notify_cmd

BOB = "codex-h-2"


import pytest


@pytest.fixture(autouse=True)
def notify_off(monkeypatch):
    monkeypatch.setattr(hubd, "load_notify_cmd", lambda log=None: [])


class Recorder:
    def __init__(self):
        self.injects = []
        self.dumps = []
        self.lines = []
        self.joined_frames = []
        self.echo_msg_ids: set[str] = set()

    def write(self, line):
        self.lines.append(line)

    def fake_inject(self, pane, wake_text, ssh_host=None):
        self.injects.append((pane, wake_text, ssh_host))

    def fake_dump(self, pane, line_count=10, ssh_host=None):
        self.dumps.append(pane)
        return "dump line 1\ndump line 2"

    def fake_capture_joined(self, pane, line_count=60, ssh_host=None):
        self.joined_frames.append(pane)
        history = "echo id=" + " id=".join(sorted(self.echo_msg_ids))
        return "\n".join([history] + [f"history line {n}" for n in range(INPUT_ZONE_LINES)] + ["input box"])


def envelope_to_bob(msg_id="m1", body="去哪读: memory/MEMORY.md 后继续批B", expect_reply=False):
    wake_text = msgfmt.compose_wake("claude-h-1", msg_id, body, expect_reply)
    return {
        "msg_id": msg_id,
        "ack_id": f"ack-{msg_id}",
        "from": "claude-h-1",
        "to": BOB,
        "body": body,
        "hop": 1,
        "created_at": 1.0,
        "expect_reply": expect_reply,
        "wake_text": wake_text,
    }


def record_for_bob(pane_id="%2", pane_pid="200", spawn_cmd=None):
    return {
        "agent_id": BOB,
        "cli": "codex",
        "host": "localhost",
        "tailnet_host": "",
        "pane_id": pane_id,
        "pane_pid": pane_pid,
        "cwd": "/tmp",
        "spawn_cmd": spawn_cmd,
    }


def wire_fake_tmux(monkeypatch, recorder):
    monkeypatch.setattr(hubd.tmuxio, "prime_injection", recorder.fake_inject)
    monkeypatch.setattr(hubd.tmuxio, "capture_bottom", recorder.fake_dump)
    monkeypatch.setattr(hubd.tmuxio, "capture_joined_bottom", recorder.fake_capture_joined)
    monkeypatch.setattr(hubd.tmuxio, "pane_created", lambda pane, ssh_host=None: 0.0)
    monkeypatch.setattr(hubd.tmuxio, "quiet_mark", lambda pane, ssh_host=None: "0")


def test_booting_pane_defers_injection(tmp_path, monkeypatch):
    recorder = Recorder()
    wire_fake_tmux(monkeypatch, recorder)
    delivery = hubd.Delivery(envelope_to_bob(), now=100.0, pane_id="%2", pane_created=95.0)

    delivery.tick(tmp_path, recorder, 102.0, True)
    assert recorder.injects == []

    delivery.tick(tmp_path, recorder, 112.0, True)
    assert len(recorder.injects) == 1


def registry_with_bob(record):
    return {"agents": {BOB: record}}


def test_happy_path_single_injection_delivers(tmp_path, monkeypatch):
    recorder = Recorder()
    wire_fake_tmux(monkeypatch, recorder)
    storage.enqueue(tmp_path, envelope_to_bob())
    reg = registry_with_bob(record_for_bob())
    deliveries = {}

    hubd.step(tmp_path, reg, deliveries, recorder, 100.0, {BOB: True})
    assert recorder.injects == []

    hubd.step(tmp_path, reg, deliveries, recorder, 102.0, {BOB: True})
    assert len(recorder.injects) == 1
    assert recorder.injects[0][0] == "%2"
    assert recorder.injects[0][1].startswith("[A2A] from=claude-h-1 id=m1\n")

    storage.write_ack(tmp_path, "ack-m1", BOB)
    hubd.step(tmp_path, reg, deliveries, recorder, 105.0, {BOB: True})

    assert deliveries == {}
    assert storage.list_queue(tmp_path, BOB) == []
    delivered_lines = [line for line in recorder.lines if line.startswith("delivered")]
    assert delivered_lines == ["delivered m1 to=codex-h-2"]


def test_delayed_ack_confirmed_without_reinjection(tmp_path, monkeypatch):
    recorder = Recorder()
    wire_fake_tmux(monkeypatch, recorder)
    storage.enqueue(tmp_path, envelope_to_bob())
    reg = registry_with_bob(record_for_bob())
    deliveries = {}

    hubd.step(tmp_path, reg, deliveries, recorder, 100.0, {BOB: True})
    hubd.step(tmp_path, reg, deliveries, recorder, 102.0, {BOB: True})
    injected_at = 102.0
    past_patience = injected_at + hubd.INJECTING_PATIENCE_SECONDS + 5.0
    hubd.step(tmp_path, reg, deliveries, recorder, past_patience, {BOB: True})
    assert len(recorder.injects) == 1
    assert deliveries[f"{BOB}/m1"].state == hubd.STATE_WAIT_CONFIRM

    storage.write_ack(tmp_path, "ack-m1", BOB)
    hubd.step(tmp_path, reg, deliveries, recorder, past_patience + 1.0, {BOB: True})

    assert len(recorder.injects) == 1
    assert storage.list_queue(tmp_path, BOB) == []


def test_injected_once_settles_unconfirmed_never_fails(tmp_path, monkeypatch):
    recorder = Recorder()
    wire_fake_tmux(monkeypatch, recorder)
    monkeypatch.setattr(hubd, "CONFIRM_PATIENCE_SECONDS", 5.0)
    storage.enqueue(tmp_path, envelope_to_bob())
    reg = registry_with_bob(record_for_bob())
    deliveries = {}

    hubd.step(tmp_path, reg, deliveries, recorder, 100.0, {BOB: True})
    hubd.step(tmp_path, reg, deliveries, recorder, 102.0, {BOB: True})
    assert len(recorder.injects) == 1

    moment = 102.0 + hubd.INJECTING_PATIENCE_SECONDS + 1.0
    hubd.step(tmp_path, reg, deliveries, recorder, moment, {BOB: True})
    assert deliveries[f"{BOB}/m1"].state == hubd.STATE_WAIT_CONFIRM
    hubd.step(tmp_path, reg, deliveries, recorder, moment + hubd.CONFIRM_PATIENCE_SECONDS + 1.0, {BOB: True})

    assert len(recorder.injects) == 1
    assert deliveries == {}
    assert not (storage.queue_dir(tmp_path, BOB) / "m1.failed").exists()
    assert (tmp_path / "history" / "m1.json").exists()
    assert any(line.startswith("unconfirmed m1") for line in recorder.lines)
    assert not any(line.startswith("FAILED m1") for line in recorder.lines)
    assert not any("bounce" in line for line in recorder.lines)


def test_offline_target_is_never_injected(tmp_path, monkeypatch):
    recorder = Recorder()
    wire_fake_tmux(monkeypatch, recorder)
    storage.enqueue(tmp_path, envelope_to_bob())
    reg = registry_with_bob(record_for_bob())

    deliveries = {}
    hubd.step(tmp_path, reg, deliveries, recorder, 100.0, {BOB: False})
    hubd.step(tmp_path, reg, deliveries, recorder, 200.0, {BOB: False})

    assert recorder.injects == []
    assert deliveries == {}
    assert storage.list_queue(tmp_path, BOB)


def test_no_delivery_path_fails_message(tmp_path, monkeypatch):
    recorder = Recorder()
    wire_fake_tmux(monkeypatch, recorder)
    storage.enqueue(tmp_path, envelope_to_bob())
    reg = registry_with_bob(record_for_bob(pane_id="", pane_pid=""))

    deliveries = {}
    hubd.step(tmp_path, reg, deliveries, recorder, 100.0, {BOB: True})

    assert recorder.injects == []
    assert (storage.queue_dir(tmp_path, BOB) / "m1.failed").exists()
    assert any("no delivery path" in line for line in recorder.lines)
    bounced = storage.list_queue(tmp_path, "claude-h-1")
    assert len(bounced) == 1
    assert bounced[0]["from"] == "hub"
    assert bounced[0]["in_reply_to"] == "m1"
    assert bounced[0]["bounce"] is True
    assert "投递失败" in bounced[0]["body"]
    assert bounced[0]["wake_text"].startswith("[A2A] from=hub")


def test_no_delivery_path_bounce_does_not_recurse(tmp_path, monkeypatch):
    recorder = Recorder()
    wire_fake_tmux(monkeypatch, recorder)
    doomed = envelope_to_bob()
    doomed["bounce"] = True
    storage.enqueue(tmp_path, doomed)
    reg = registry_with_bob(record_for_bob(pane_id="", pane_pid=""))

    deliveries = {}
    hubd.step(tmp_path, reg, deliveries, recorder, 100.0, {BOB: True})

    assert (storage.queue_dir(tmp_path, BOB) / "m1.failed").exists()
    assert storage.list_queue(tmp_path, "claude-h-1") == []
    assert storage.list_queue(tmp_path, "hub") == []


class SpawnPopen:
    def __init__(self, returncode):
        self.returncode = returncode

    def __call__(self, command, **kwargs):
        proc = FakeProc(self.returncode)
        self.proc = proc
        return proc


def wire_fake_spawn(monkeypatch, returncode):
    spawner = SpawnPopen(returncode)
    monkeypatch.setattr(hubd.subprocess, "Popen", spawner)
    return spawner


def test_spawn_delivery_via_one_shot_command(tmp_path, monkeypatch):
    recorder = Recorder()
    wire_fake_tmux(monkeypatch, recorder)
    wire_fake_spawn(monkeypatch, 0)
    storage.enqueue(tmp_path, envelope_to_bob())
    reg = registry_with_bob(record_for_bob(pane_id="", pane_pid="", spawn_cmd=["echo"]))
    deliveries = {}

    hubd.step(tmp_path, reg, deliveries, recorder, 100.0, {BOB: True})
    hubd.step(tmp_path, reg, deliveries, recorder, 102.0, {BOB: True})
    hubd.step(tmp_path, reg, deliveries, recorder, 103.0, {BOB: True})

    assert recorder.injects == []
    assert any("spawn exit=0" in line for line in recorder.lines)
    delivery_state = deliveries[f"{BOB}/m1"].state
    assert delivery_state == hubd.STATE_WAIT_ACK

    storage.write_ack(tmp_path, "ack-m1", BOB)
    hubd.step(tmp_path, reg, deliveries, recorder, 103.0, {BOB: True})
    assert storage.list_queue(tmp_path, BOB) == []


def test_spawn_failure_fails_message(tmp_path, monkeypatch):
    recorder = Recorder()
    wire_fake_tmux(monkeypatch, recorder)
    wire_fake_spawn(monkeypatch, 1)
    storage.enqueue(tmp_path, envelope_to_bob())
    reg = registry_with_bob(record_for_bob(pane_id="", pane_pid="", spawn_cmd=["false"]))
    deliveries = {}

    hubd.step(tmp_path, reg, deliveries, recorder, 100.0, {BOB: True})
    hubd.step(tmp_path, reg, deliveries, recorder, 102.0, {BOB: True})
    hubd.step(tmp_path, reg, deliveries, recorder, 103.0, {BOB: True})

    assert deliveries == {}
    assert (storage.queue_dir(tmp_path, BOB) / "m1.failed").exists()


def test_sweep_liveness_reports_slot_and_spawn(tmp_path, monkeypatch):
    recorder = Recorder()
    pane_record = record_for_bob()
    pane_record["slot"] = "pi:codex"
    spawn_record = record_for_bob(pane_id="", pane_pid="", spawn_cmd=["echo"])
    spawn_record["agent_id"] = "codex-win-9"
    reg = {"agents": {BOB: pane_record, "codex-win-9": spawn_record}}

    monkeypatch.setattr(hubd.tmuxio, "slot_pane_id", lambda slot, ssh=None: "%2" if slot == "pi:codex" else "")
    online = hubd.sweep_liveness(reg, tmp_path, recorder, {}, {}, 100.0)

    assert online[BOB] is True
    assert online["codex-win-9"] is True

    monkeypatch.setattr(hubd.tmuxio, "slot_pane_id", lambda slot, ssh=None: "")
    online = hubd.sweep_liveness({"agents": {BOB: pane_record}}, tmp_path, recorder, online, {}, 101.0)
    assert online[BOB] is False
    assert any("offline" in line for line in recorder.lines)


def test_sweep_liveness_refreshes_pane_anchor_on_slot(tmp_path, monkeypatch):
    recorder = Recorder()
    moved = record_for_bob()
    moved["slot"] = "pi:codex"
    reg = {"agents": {BOB: moved}}
    monkeypatch.setattr(hubd.tmuxio, "slot_pane_id", lambda slot, ssh=None: "%9")
    monkeypatch.setattr(hubd.tmuxio, "pane_pid", lambda pane, ssh=None: "777")
    monkeypatch.setattr(hubd.tmuxio, "pane_current_command", lambda pane, ssh=None: "codex")

    online = hubd.sweep_liveness(reg, tmp_path, recorder, {}, {}, 100.0)

    assert online[BOB] is True
    assert reg["agents"][BOB]["pane_id"] == "%9"
    assert reg["agents"][BOB]["pane_pid"] == "777"


def test_sweep_liveness_rejects_stranger_pane_in_same_slot(tmp_path, monkeypatch):
    recorder = Recorder()
    moved = record_for_bob()
    moved["slot"] = "pi:codex"
    reg = {"agents": {BOB: moved}}
    snap = {
        "": {
            "slots": {"pi:codex": "%52"},
            "panes": {"%52": {"pane_pid": "900", "cwd": "/tmp", "slot": "pi:codex", "command": "bash"}},
        }
    }

    online = hubd.sweep_liveness(reg, tmp_path, recorder, {}, {}, 100.0, snap)

    assert online[BOB] is False
    assert reg["agents"][BOB]["pane_id"] == "%2"
    assert reg["agents"][BOB]["pane_pid"] == "200"
    assert any("identity-mismatch" in line and "bash" in line for line in recorder.lines)


def test_sweep_liveness_uses_ssh_alias(tmp_path, monkeypatch):
    remote = record_for_bob()
    remote["ssh_alias"] = "host-b"
    seen = {}

    def fake_matches(pane, pid, ssh=None):
        seen["ssh"] = ssh
        return True

    monkeypatch.setattr(hubd.tmuxio, "pane_pid_matches", fake_matches)
    cache = {}
    online = hubd.sweep_liveness({"agents": {BOB: remote}}, tmp_path, Recorder(), {}, cache, 100.0)
    assert seen["ssh"] == "host-b"
    assert online[BOB] is True

    seen["ssh"] = None
    online = hubd.sweep_liveness({"agents": {BOB: remote}}, tmp_path, Recorder(), online, cache, 102.0)
    assert online[BOB] is True
    assert seen["ssh"] is None

    online = hubd.sweep_liveness({"agents": {BOB: remote}}, tmp_path, Recorder(), online, cache, 100.0 + hubd.REMOTE_LIVENESS_SECONDS + 1.0)
    assert seen["ssh"] == "host-b"


def test_build_delivery_ssh_alias_routes_remote():
    record = record_for_bob()
    record["ssh_alias"] = "host-b"
    delivery = hubd.build_delivery(envelope_to_bob(), record, 100.0)
    assert delivery is not None
    assert delivery.pane_id == "%2"
    assert delivery.ssh_host == "host-b"


def test_build_delivery_routes_to_instance_pane(monkeypatch):
    monkeypatch.setattr(hubd.tmuxio, "pane_created", lambda pane, ssh_host=None: 0.0)
    record = record_for_bob()
    record["instances"] = {
        "olddd000": {"pane_id": "%1", "pane_pid": "100", "slot": "s:old"},
        "aaaabbbb": {"pane_id": "%9", "pane_pid": "900", "slot": "s:new"},
    }
    envelope = envelope_to_bob()
    envelope["to_instance"] = "aaaabbbb"

    delivery = hubd.build_delivery(envelope, record, 100.0)

    assert delivery is not None
    assert delivery.pane_id == "%9"


def test_build_delivery_unknown_instance_falls_back_to_main_anchor(monkeypatch):
    monkeypatch.setattr(hubd.tmuxio, "pane_created", lambda pane, ssh_host=None: 0.0)
    record = record_for_bob()
    record["instances"] = {"aaaabbbb": {"pane_id": "%9", "pane_pid": "900", "slot": "s:new"}}
    envelope = envelope_to_bob()
    envelope["to_instance"] = "ghostkey"

    delivery = hubd.build_delivery(envelope, record, 100.0)

    assert delivery is not None
    assert delivery.pane_id == "%2"


def test_sweep_liveness_prunes_dead_instance_entries(tmp_path, monkeypatch):
    recorder = Recorder()
    twin = record_for_bob()
    twin["instances"] = {
        "aaaabbbb": {"pane_id": "%9", "pane_pid": "900", "slot": "s:w9"},
        "olddd000": {"pane_id": "%1", "pane_pid": "100", "slot": "s:w1"},
    }
    reg = {"agents": {BOB: twin}}
    snap = {
        "": {
            "slots": {"s:w9": "%9"},
            "panes": {
                "%2": {"pane_pid": "200", "cwd": "/tmp", "slot": "s:w9", "command": "codex"},
                "%9": {"pane_pid": "900", "cwd": "/tmp", "slot": "s:w9", "command": "codex"},
            },
        }
    }

    hubd.sweep_liveness(reg, tmp_path, recorder, {}, {}, 100.0, snap)

    assert set(reg["agents"][BOB]["instances"]) == {"aaaabbbb"}
    assert any("instance-pruned" in line and "olddd000" in line for line in recorder.lines)


def test_sweep_tool_silence_warns_on_stale_last_seen():
    recorder = Recorder()
    stale = record_for_bob()
    stale["last_seen"] = 100.0 - hubd.TOOL_SILENT_SECONDS - 1
    fresh = record_for_bob()
    fresh["agent_id"] = "codex-fresh-9"
    fresh["last_seen"] = 99.0
    reg = {"agents": {BOB: stale, "codex-fresh-9": fresh}}
    online = {BOB: True, "codex-fresh-9": True}

    silent = hubd.sweep_tool_silence(reg, recorder, set(), 100.0, online)
    assert silent == {BOB}
    assert any(line.startswith(f"tool-silent {BOB}") for line in recorder.lines)

    again = hubd.sweep_tool_silence(reg, recorder, silent, 102.0, online)
    assert again == {BOB}
    assert len([line for line in recorder.lines if line.startswith("tool-silent")]) == 1

    offline = hubd.sweep_tool_silence(reg, Recorder(), set(), 100.0, {BOB: False})
    assert offline == set()


def test_remote_ack_arrival_via_ssh(tmp_path, monkeypatch):
    recorder = Recorder()
    monkeypatch.setattr(hubd.tmuxio, "prime_injection", recorder.fake_inject)
    monkeypatch.setattr(hubd.tmuxio, "capture_bottom", recorder.fake_dump)
    monkeypatch.setattr(hubd.tmuxio, "capture_joined_bottom", recorder.fake_capture_joined)
    monkeypatch.setattr(hubd.tmuxio, "pane_created", lambda pane, ssh_host=None: 0.0)
    monkeypatch.setattr(hubd.tmuxio, "quiet_mark", lambda pane, ssh_host=None: "0")
    acks = set()
    monkeypatch.setattr(
        hubd.sshio,
        "remote_ack_state",
        lambda host, ack: hubd.sshio.REMOTE_ACK_PRESENT if ack in acks else hubd.sshio.REMOTE_ACK_ABSENT,
    )
    storage.enqueue(tmp_path, envelope_to_bob())
    record = record_for_bob()
    record["ssh_alias"] = "host-b"
    reg = registry_with_bob(record)
    deliveries = {}

    hubd.step(tmp_path, reg, deliveries, recorder, 100.0, {BOB: True})
    hubd.step(tmp_path, reg, deliveries, recorder, 102.0, {BOB: True})
    assert len(recorder.injects) == 1
    assert recorder.injects[0][2] == "host-b"

    acks.add("ack-m1")
    hubd.step(tmp_path, reg, deliveries, recorder, 103.0, {BOB: True})
    assert storage.list_queue(tmp_path, BOB) == []
    assert any(line.startswith("delivered m1") for line in recorder.lines)


def test_remote_ack_unreachable_suspends_ack_timeout(tmp_path, monkeypatch):
    recorder = Recorder()
    monkeypatch.setattr(hubd.tmuxio, "capture_bottom", recorder.fake_dump)
    probe = {"state": hubd.sshio.REMOTE_ACK_UNREACHABLE}
    monkeypatch.setattr(hubd.sshio, "remote_ack_state", lambda host, ack: probe["state"])
    envelope = envelope_to_bob()
    storage.enqueue(tmp_path, envelope)
    delivery = hubd.Delivery(envelope, 100.0, pane_id="%0", ssh_host="host-b")
    delivery.state = hubd.STATE_WAIT_ACK
    delivery.injected_at = 100.0

    delivery.tick(tmp_path, recorder, 100.0 + hubd.ACK_TIMEOUT_SECONDS + 30.0, True)
    assert delivery.state == hubd.STATE_WAIT_ACK
    assert storage.list_queue(tmp_path, BOB) != []

    confirm = hubd.Delivery(envelope_to_bob(), 100.0, pane_id="%0", ssh_host="host-b")
    confirm.state = hubd.STATE_WAIT_CONFIRM
    confirm.state_since = 100.0
    confirm.tick(tmp_path, recorder, 100.0 + hubd.CONFIRM_PATIENCE_SECONDS + 30.0, True)
    assert confirm.state == hubd.STATE_WAIT_CONFIRM

    probe["state"] = hubd.sshio.REMOTE_ACK_PRESENT
    delivery.tick(tmp_path, recorder, 231.0, True)
    assert delivery.state == hubd.STATE_DONE
    assert storage.list_queue(tmp_path, BOB) == []


def wire_busy_gate(monkeypatch, mark="0", busy=False):
    monkeypatch.setattr(hubd.tmuxio, "quiet_mark", lambda pane, ssh=None: mark)
    monkeypatch.setattr(hubd.tmuxio, "busy_probe_frame", lambda pane, ssh=None: "frame-a")
    monkeypatch.setattr(hubd.tmuxio, "frame_grew_since", lambda first, pane, ssh=None: busy)


def test_busy_pane_defers_injection_without_round_cost(tmp_path, monkeypatch):
    recorder = Recorder()
    wire_fake_tmux(monkeypatch, recorder)
    wire_busy_gate(monkeypatch, mark="", busy=True)
    storage.enqueue(tmp_path, envelope_to_bob())
    reg = registry_with_bob(record_for_bob())
    deliveries = {}

    hubd.step(tmp_path, reg, deliveries, recorder, 100.0, {BOB: True})
    hubd.step(tmp_path, reg, deliveries, recorder, 102.0, {BOB: True})
    hubd.step(tmp_path, reg, deliveries, recorder, 105.0, {BOB: True})

    assert recorder.injects == []
    assert deliveries[f"{BOB}/m1"].state == hubd.STATE_SETTLING
    assert len([line for line in recorder.lines if line.startswith("deferred m1")]) == 1

    wire_busy_gate(monkeypatch, busy=False)
    hubd.step(tmp_path, reg, deliveries, recorder, 108.0, {BOB: True})
    hubd.step(tmp_path, reg, deliveries, recorder, 110.0, {BOB: True})
    assert len(recorder.injects) == 1
    assert recorder.injects[0][1].startswith("[A2A] from=claude-h-1 id=m1")


def test_quiet_mark_blocks_and_skips_probe(tmp_path, monkeypatch):
    recorder = Recorder()
    wire_fake_tmux(monkeypatch, recorder)
    probes = []
    monkeypatch.setattr(hubd.tmuxio, "quiet_mark", lambda pane, ssh=None: "1")
    monkeypatch.setattr(hubd.tmuxio, "busy_probe_frame", lambda pane, ssh=None: probes.append(pane) or "frame-a")
    delivery = hubd.Delivery(envelope_to_bob(), now=100.0, pane_id="%2")

    delivery.tick(tmp_path, recorder, 102.0, True)
    delivery.tick(tmp_path, recorder, 105.0, True)

    assert recorder.injects == []
    assert probes == []
    assert delivery.state == hubd.STATE_SETTLING


def test_quiet_mark_zero_overrides_busy_probe(tmp_path, monkeypatch):
    recorder = Recorder()
    wire_fake_tmux(monkeypatch, recorder)
    monkeypatch.setattr(hubd.tmuxio, "quiet_mark", lambda pane, ssh=None: "0")
    monkeypatch.setattr(hubd.tmuxio, "busy_probe_frame", lambda pane, ssh=None: "frame-a")
    monkeypatch.setattr(hubd.tmuxio, "frame_grew_since", lambda first, pane, ssh=None: True)
    delivery = hubd.Delivery(envelope_to_bob(), now=100.0, pane_id="%2")

    delivery.tick(tmp_path, recorder, 102.0, True)
    delivery.tick(tmp_path, recorder, 103.0, True)
    delivery.tick(tmp_path, recorder, 106.0, True)

    assert len(recorder.injects) == 1
    assert delivery.state == hubd.STATE_WAIT_CONFIRM


def test_spawn_delivery_skips_busy_gate(tmp_path, monkeypatch):
    recorder = Recorder()
    wire_fake_tmux(monkeypatch, recorder)
    wire_fake_spawn(monkeypatch, 0)
    wire_busy_gate(monkeypatch, busy=True)
    storage.enqueue(tmp_path, envelope_to_bob())
    reg = registry_with_bob(record_for_bob(pane_id="", pane_pid="", spawn_cmd=["echo"]))
    deliveries = {}

    hubd.step(tmp_path, reg, deliveries, recorder, 100.0, {BOB: True})
    hubd.step(tmp_path, reg, deliveries, recorder, 102.0, {BOB: True})
    hubd.step(tmp_path, reg, deliveries, recorder, 103.0, {BOB: True})

    assert any("spawn exit=0" in line for line in recorder.lines)


class ToastPopen:
    def __init__(self, returncode=0):
        self.returncode = returncode
        self.calls = []

    def __call__(self, command, **kwargs):
        proc = FakeProc(self.returncode)
        self.calls.append((command, proc))
        return proc


class FakeProc:
    def __init__(self, returncode):
        self.returncode = returncode
        self.stdin = FakePipe()

    def poll(self):
        return self.returncode

    def terminate(self):
        pass


class RecordingPool:
    def __init__(self):
        self.spawned = []

    def spawn(self, cmd, payload, event, log):
        self.spawned.append((cmd, payload, event))

    def reap(self, log, now):
        pass


class FakePipe:
    def __init__(self):
        self.payload = b""

    def write(self, data):
        self.payload += data

    def close(self):
        pass


def test_notify_delivered_fires_cmd_with_json(tmp_path, monkeypatch):
    recorder = Recorder()
    wire_fake_tmux(monkeypatch, recorder)
    wire_busy_gate(monkeypatch)
    monkeypatch.setattr(hubd, "load_notify_cmd", lambda log=None: ["toast"])
    toasts = ToastPopen()
    monkeypatch.setattr(hubd.subprocess, "Popen", toasts)
    storage.enqueue(tmp_path, envelope_to_bob())
    reg = registry_with_bob(record_for_bob())
    deliveries = {}

    hubd.step(tmp_path, reg, deliveries, recorder, 100.0, {BOB: True})
    hubd.step(tmp_path, reg, deliveries, recorder, 102.0, {BOB: True})
    storage.write_ack(tmp_path, "ack-m1", BOB)
    hubd.step(tmp_path, reg, deliveries, recorder, 105.0, {BOB: True})

    events = [json.loads(proc.stdin.payload)["event"] for _, proc in toasts.calls]
    assert events == ["delivered"]
    assert toasts.calls[0][0] == ["toast"]


def test_silent_consumer_never_fires_delivery_failed(tmp_path, monkeypatch):
    recorder = Recorder()
    wire_fake_tmux(monkeypatch, recorder)
    wire_busy_gate(monkeypatch)
    monkeypatch.setattr(hubd, "load_notify_cmd", lambda log=None: ["toast"])
    pool = RecordingPool()
    monkeypatch.setattr(hubd, "NOTIFY_POOL", pool)
    monkeypatch.setattr(hubd, "CONFIRM_PATIENCE_SECONDS", 5.0)
    storage.enqueue(tmp_path, envelope_to_bob())
    reg = registry_with_bob(record_for_bob())
    deliveries = {}

    hubd.step(tmp_path, reg, deliveries, recorder, 100.0, {BOB: True})
    hubd.step(tmp_path, reg, deliveries, recorder, 102.0, {BOB: True})
    assert len(recorder.injects) == 1

    moment = 102.0 + hubd.INJECTING_PATIENCE_SECONDS + 1.0
    hubd.step(tmp_path, reg, deliveries, recorder, moment, {BOB: True})
    hubd.step(tmp_path, reg, deliveries, recorder, moment + hubd.CONFIRM_PATIENCE_SECONDS + 1.0, {BOB: True})

    assert not pool.spawned
    assert not storage.list_queue(tmp_path, "claude-h-1")
    assert not any(line.startswith("FAILED m1") for line in recorder.lines)


def test_spawn_ack_timeout_notifies_and_bounces(tmp_path, monkeypatch):
    recorder = Recorder()
    wire_fake_tmux(monkeypatch, recorder)
    wire_fake_spawn(monkeypatch, 0)
    monkeypatch.setattr(hubd, "load_notify_cmd", lambda log=None: ["toast"])
    pool = RecordingPool()
    monkeypatch.setattr(hubd, "NOTIFY_POOL", pool)
    storage.enqueue(tmp_path, envelope_to_bob())
    reg = registry_with_bob(record_for_bob(pane_id="", pane_pid="", spawn_cmd=["echo"]))
    deliveries = {}

    moment = 100.0
    hubd.step(tmp_path, reg, deliveries, recorder, moment, {BOB: True})
    moment += 2.0
    hubd.step(tmp_path, reg, deliveries, recorder, moment, {BOB: True})
    moment += 1.0
    hubd.step(tmp_path, reg, deliveries, recorder, moment, {BOB: True})
    assert deliveries[f"{BOB}/m1"].state == hubd.STATE_WAIT_ACK

    moment += hubd.SPAWN_ACK_TIMEOUT_SECONDS + 1.0
    hubd.step(tmp_path, reg, deliveries, recorder, moment, {BOB: True})

    assert deliveries == {}
    assert (storage.queue_dir(tmp_path, BOB) / "m1.failed").exists()
    assert any(line.startswith("FAILED m1") and "ack timeout" in line for line in recorder.lines)
    events = [json.loads(payload) for _, payload, _ in pool.spawned]
    assert [item["event"] for item in events] == ["delivery-failed"]
    assert events[0]["reason"] == "ack timeout after retries"
    bounced = storage.list_queue(tmp_path, "claude-h-1")
    assert len(bounced) == 1 and bounced[0]["in_reply_to"] == "m1"


def test_receipt_then_confirm_two_layer(tmp_path, monkeypatch):
    recorder = Recorder()
    wire_fake_tmux(monkeypatch, recorder)
    wire_busy_gate(monkeypatch)
    storage.enqueue(tmp_path, envelope_to_bob())
    reg = registry_with_bob(record_for_bob())
    deliveries = {}

    hubd.step(tmp_path, reg, deliveries, recorder, 100.0, {BOB: True})
    hubd.step(tmp_path, reg, deliveries, recorder, 102.0, {BOB: True})
    assert recorder.injects and deliveries[f"{BOB}/m1"].state == hubd.STATE_INJECTING
    hubd.step(tmp_path, reg, deliveries, recorder, 103.0, {BOB: True})
    hubd.step(tmp_path, reg, deliveries, recorder, 106.0, {BOB: True})
    assert deliveries[f"{BOB}/m1"].state == hubd.STATE_WAIT_CONFIRM
    receipt_lines = [line for line in recorder.lines if line.startswith("receipt m1")]
    assert receipt_lines and "Enter 阶梯完成" in receipt_lines[0]

    storage.write_ack(tmp_path, "ack-m1", BOB)
    hubd.step(tmp_path, reg, deliveries, recorder, 106.0, {BOB: True})
    assert deliveries == {}
    assert storage.list_queue(tmp_path, BOB) == []
    assert (tmp_path / "history" / "m1.json").exists()


def test_notification_message_stops_at_receipt(tmp_path, monkeypatch):
    recorder = Recorder()
    wire_fake_tmux(monkeypatch, recorder)
    wire_busy_gate(monkeypatch)
    monkeypatch.setattr(hubd, "CONFIRM_PATIENCE_SECONDS", 5.0)
    storage.enqueue(tmp_path, envelope_to_bob())
    reg = registry_with_bob(record_for_bob())
    deliveries = {}

    hubd.step(tmp_path, reg, deliveries, recorder, 100.0, {BOB: True})
    hubd.step(tmp_path, reg, deliveries, recorder, 102.0, {BOB: True})
    hubd.step(tmp_path, reg, deliveries, recorder, 103.0, {BOB: True})
    hubd.step(tmp_path, reg, deliveries, recorder, 105.0, {BOB: True})
    hubd.step(tmp_path, reg, deliveries, recorder, 106.0, {BOB: True})

    hubd.step(tmp_path, reg, deliveries, recorder, 111.0, {BOB: True})
    assert deliveries == {}
    failed = storage.queue_dir(tmp_path, BOB) / "m1.failed"
    assert not failed.exists()
    assert (tmp_path / "history" / "m1.json").exists()
    assert any(line.startswith("unconfirmed m1") for line in recorder.lines)
    assert not any(line.startswith("FAILED m1") for line in recorder.lines)


def test_expect_reply_timeout_marks_failed_and_notifies(tmp_path, monkeypatch):
    recorder = Recorder()
    wire_fake_tmux(monkeypatch, recorder)
    wire_busy_gate(monkeypatch)
    monkeypatch.setattr(hubd, "CONFIRM_PATIENCE_SECONDS", 5.0)
    monkeypatch.setattr(hubd, "load_notify_cmd", lambda log=None: ["toast"])
    pool = RecordingPool()
    monkeypatch.setattr(hubd, "NOTIFY_POOL", pool)
    storage.enqueue(tmp_path, envelope_to_bob(expect_reply=True))
    reg = registry_with_bob(record_for_bob())
    deliveries = {}

    hubd.step(tmp_path, reg, deliveries, recorder, 100.0, {BOB: True})
    hubd.step(tmp_path, reg, deliveries, recorder, 102.0, {BOB: True})
    recorder.echo_msg_ids.add("m1")
    hubd.step(tmp_path, reg, deliveries, recorder, 103.0, {BOB: True})
    hubd.step(tmp_path, reg, deliveries, recorder, 105.0, {BOB: True})
    hubd.step(tmp_path, reg, deliveries, recorder, 106.0, {BOB: True})

    hubd.step(tmp_path, reg, deliveries, recorder, 111.0, {BOB: True})

    assert deliveries == {}
    assert (storage.queue_dir(tmp_path, BOB) / "m1.failed").exists()
    assert not (tmp_path / "history" / "m1.json").exists()
    assert any(line.startswith("reply-missing m1") for line in recorder.lines)
    events = [json.loads(payload) for _, payload, _ in pool.spawned]
    assert [item["event"] for item in events] == ["reply-missing"]
    assert storage.list_queue(tmp_path, "claude-h-1") == []


def test_ack_before_echo_skips_receipt_layer(tmp_path, monkeypatch):
    recorder = Recorder()
    wire_fake_tmux(monkeypatch, recorder)
    wire_busy_gate(monkeypatch)
    storage.enqueue(tmp_path, envelope_to_bob())
    reg = registry_with_bob(record_for_bob())
    deliveries = {}

    hubd.step(tmp_path, reg, deliveries, recorder, 100.0, {BOB: True})
    hubd.step(tmp_path, reg, deliveries, recorder, 102.0, {BOB: True})
    storage.write_ack(tmp_path, "ack-m1", BOB)
    hubd.step(tmp_path, reg, deliveries, recorder, 103.0, {BOB: True})

    assert deliveries == {}
    assert any(line.startswith("delivered m1") for line in recorder.lines)


def test_notify_failure_is_swallowed_and_logged(monkeypatch):
    recorder = Recorder()
    wire_fake_tmux(monkeypatch, recorder)
    wire_busy_gate(monkeypatch)
    monkeypatch.setattr(hubd, "load_notify_cmd", lambda log=None: ["toast"])

    class Exploder:
        def __call__(self, command, **kwargs):
            raise OSError("toast gone")

    monkeypatch.setattr(hubd.subprocess, "Popen", Exploder())
    hubd.notify(recorder, "agent-offline", agent_id=BOB)
    assert any(line.startswith("notify agent-offline error") for line in recorder.lines)


def test_paneless_online_pull_only_last_seen(tmp_path):
    zcode = record_for_bob()
    zcode["cli"] = "zcode"
    zcode["pane_id"] = ""
    zcode["spawn_cmd"] = None
    zcode["last_seen"] = time.time() - 60
    assert hubd.paneless_online(zcode) is True

    stale = dict(zcode)
    stale["last_seen"] = time.time() - hubd.PANELESS_ACTIVE_SECONDS - 1
    assert hubd.paneless_online(stale) is False

    stranger = dict(zcode)
    stranger["cli"] = "claude"
    assert hubd.paneless_online(stranger) is False

    daemon = record_for_bob()
    daemon["pane_id"] = ""
    daemon["codex_bin"] = "/usr/local/bin/codex"
    daemon["codex_home"] = "/home/u/.codex"
    daemon["codex_thread"] = "t-1"
    assert hubd.paneless_online(daemon) is True


def test_prune_keeps_pull_only_record_with_pending_mail(tmp_path, monkeypatch):
    recorder = Recorder()
    storage.enqueue(tmp_path, envelope_to_bob())
    reg = {"agents": {BOB: {**record_for_bob(), "cli": "zcode", "pane_id": "", "spawn_cmd": None}}}

    assert hubd.prune_registry(reg, tmp_path, recorder, {BOB: False}, 99999.0) == []
    assert BOB in reg["agents"]
    assert storage.read_msg(tmp_path, BOB, "m1") is not None

    storage.archive_msg(tmp_path, BOB, "m1")
    assert hubd.prune_registry(reg, tmp_path, recorder, {BOB: False}, 99999.0) == [BOB]


def test_prune_registry_archives_dead_stale_agents(tmp_path, monkeypatch):
    recorder = Recorder()
    dead = record_for_bob()
    dead["last_seen"] = 100.0 - hubd.REGISTRY_PRUNE_TTL - 1
    alive_pane = record_for_bob()
    alive_pane["agent_id"] = "codex-fresh-9"
    alive_pane["last_seen"] = 99.0
    reg = {"agents": {BOB: dead, "codex-fresh-9": alive_pane}}

    pruned = hubd.prune_registry(reg, tmp_path, recorder, {BOB: False, "codex-fresh-9": True}, 100.0)

    assert pruned == [BOB]
    assert BOB not in reg["agents"] and "codex-fresh-9" in reg["agents"]
    archive = tmp_path / "history" / "registry-pruned.jsonl"
    assert BOB in archive.read_text()

    fresh_dead = record_for_bob()
    fresh_dead["last_seen"] = 99.0
    reg2 = {"agents": {BOB: fresh_dead}}
    assert hubd.prune_registry(reg2, tmp_path, recorder, {BOB: False}, 100.0) == [BOB]

    remote_dead = record_for_bob()
    remote_dead["ssh_alias"] = "host-b"
    remote_dead["last_seen"] = 99.0
    reg3 = {"agents": {BOB: remote_dead}}
    assert hubd.prune_registry(reg3, tmp_path, recorder, {BOB: False}, 100.0) == []
    remote_dead["last_seen"] = 100.0 - hubd.REGISTRY_PRUNE_TTL - 1
    assert hubd.prune_registry(reg3, tmp_path, recorder, {BOB: False}, 100.0) == []
    storage.enqueue(tmp_path, envelope_to_bob())
    remote_dead["last_seen"] = 100.0 - hubd.REGISTRY_PRUNE_REMOTE_TTL - 1
    assert hubd.prune_registry(reg3, tmp_path, recorder, {BOB: False}, 100.0) == []
    storage.discard_msg(tmp_path, BOB, envelope_to_bob()["msg_id"])
    assert hubd.prune_registry(reg3, tmp_path, recorder, {BOB: False}, 100.0) == [BOB]

    unknown_alive = record_for_bob()
    reg4 = {"agents": {BOB: unknown_alive}}
    assert hubd.prune_registry(reg4, tmp_path, recorder, {}, 100.0) == []

    revivable = record_for_bob()
    revivable["cli"] = "claude"
    revivable["slot"] = "s:work"
    revivable["last_seen"] = 99.0
    reg5 = {"agents": {BOB: revivable}}
    assert hubd.prune_registry(reg5, tmp_path, recorder, {BOB: False}, 100.0) == []
    assert BOB in reg5["agents"]
    revivable["last_seen"] = 100.0 - hubd.REGISTRY_PRUNE_TTL - 1
    assert hubd.prune_registry(reg5, tmp_path, recorder, {BOB: False}, 100.0) == [BOB]


def test_prune_settles_inflight_and_bounces(tmp_path, monkeypatch):
    recorder = Recorder()
    storage.enqueue(tmp_path, envelope_to_bob())
    reg = {"agents": {BOB: record_for_bob()}}
    deliveries = {f"{BOB}/m1": hubd.Delivery(envelope_to_bob(), now=100.0, pane_id="%2")}

    pruned = hubd.prune_registry(reg, tmp_path, recorder, {BOB: False}, 100.0, None, deliveries)

    assert pruned == [BOB]
    assert (storage.queue_dir(tmp_path, BOB) / "m1.failed").exists()
    assert deliveries == {}
    bounced = storage.list_queue(tmp_path, "claude-h-1")
    assert len(bounced) == 1
    assert "recipient deregistered" in bounced[0]["body"]
    assert any("处置在途邮件 1 条" in line for line in recorder.lines)


def test_orphan_sweep_settles_unregistered_queue(tmp_path, monkeypatch):
    recorder = Recorder()
    ghost_env = envelope_to_bob()
    ghost_env["to"] = "ghost-9"
    storage.enqueue(tmp_path, ghost_env)
    reg = {"agents": {BOB: record_for_bob()}}

    swept = hubd.sweep_orphan_queues(tmp_path, recorder, reg)

    assert swept == ["ghost-9"]
    assert (storage.queue_dir(tmp_path, "ghost-9") / "m1.failed").exists()
    assert len(storage.list_queue(tmp_path, "claude-h-1")) == 1
    assert any(line.startswith("orphan-sweep ghost-9") for line in recorder.lines)


def test_orphan_sweep_relays_crosshost_mail_to_peer_home(tmp_path, monkeypatch):
    recorder = Recorder()
    from common import peers as peers_store, sshio

    peers_store.add_peer(tmp_path, "peerhost")
    crosshost_env = envelope_to_bob()
    crosshost_env["to"] = "zcode-peerhost-9"
    storage.enqueue(tmp_path, crosshost_env)
    reg = {"agents": {BOB: record_for_bob()}}
    monkeypatch.setattr(hubd.sshio, "write_remote_envelope", lambda alias, envelope: sshio.REMOTE_OK)

    swept = hubd.sweep_orphan_queues(tmp_path, recorder, reg)

    assert swept == ["zcode-peerhost-9"]
    assert not (storage.queue_dir(tmp_path, "zcode-peerhost-9") / "m1.failed").exists()
    assert (tmp_path / "history" / "m1.json").exists()
    assert any("孤儿信按 host 段归 home hub(peerhost)" in line for line in recorder.lines)


def test_failed_corpses_morgued_only_after_ttl(tmp_path, monkeypatch):
    recorder = Recorder()
    paths.ensure_layout(tmp_path)
    corpse = storage.queue_dir(tmp_path, BOB) / "m1.failed"
    corpse.parent.mkdir(parents=True, exist_ok=True)
    corpse.write_text("{}")
    stale = time.time() - hubd.FAILED_MORGUE_SECONDS - 1.0
    import os

    os.utime(corpse, (stale, stale))

    moved = hubd.sweep_failed_corpses(tmp_path, recorder, time.time())

    assert moved == 1
    assert not corpse.exists()
    assert (tmp_path / "forensics" / "queue-failed" / BOB / "m1.failed").exists()
    fresh = storage.queue_dir(tmp_path, BOB) / "m2.failed"
    fresh.write_text("{}")
    assert hubd.sweep_failed_corpses(tmp_path, recorder, time.time()) == 0
    assert fresh.exists()


def test_build_delivery_native_without_alive_signal(tmp_path):
    paths.ensure_layout(tmp_path)
    record = record_for_bob()
    record["cli"] = "pi"

    delivery = hubd.build_delivery(envelope_to_bob(), record, 100.0, tmp_path)

    assert delivery is not None and delivery.native


def test_step_relays_backlogged_mail_for_remote_native_inbox_agent(tmp_path, monkeypatch):
    recorder = Recorder()
    from common import sshio

    paths.ensure_layout(tmp_path)
    storage.enqueue(tmp_path, envelope_to_bob())
    record = record_for_bob()
    record["cli"] = "pi"
    record["ssh_alias"] = "host-a"
    reg = {"agents": {BOB: record}}
    monkeypatch.setattr(hubd.sshio, "write_remote_envelope", lambda alias, envelope: sshio.REMOTE_OK)

    hubd.step(tmp_path, reg, {}, recorder, 100.0, {BOB: True})

    assert not storage.list_queue(tmp_path, BOB)
    assert (tmp_path / "history" / "m1.json").exists()
    assert not any("via=pane" in line or "inject" in line for line in recorder.lines)


def test_step_relays_backlogged_mail_for_remote_pull_only_agent(tmp_path, monkeypatch):
    recorder = Recorder()
    from common import sshio

    paths.ensure_layout(tmp_path)
    storage.enqueue(tmp_path, envelope_to_bob())
    record = record_for_bob()
    record["cli"] = "zcode"
    record["ssh_alias"] = "host-a"
    record["pane_id"] = ""
    reg = {"agents": {BOB: record}}
    monkeypatch.setattr(hubd.sshio, "write_remote_envelope", lambda alias, envelope: sshio.REMOTE_OK)

    hubd.step(tmp_path, reg, {}, recorder, 100.0, {BOB: True})

    assert not storage.list_queue(tmp_path, BOB)
    assert (tmp_path / "history" / "m1.json").exists()
    assert any("relayed m1" in line and "home hub(host-a)" in line for line in recorder.lines)


def test_mark_failed_tolerates_missing_source(tmp_path):
    paths.ensure_layout(tmp_path)

    failed_path = storage.mark_failed(tmp_path, BOB, "ghost")

    assert not failed_path.exists()
    assert not storage.msg_in_queue(tmp_path, BOB, "ghost")


def test_orphan_sweep_respects_respawn_race(tmp_path, monkeypatch):
    recorder = Recorder()
    ghost_env = envelope_to_bob()
    ghost_env["to"] = "ghost-9"
    storage.enqueue(tmp_path, ghost_env)
    registry.upsert(tmp_path, "ghost-9", {"cli": "codex", "pane_id": "%5"})
    reg = {"agents": {BOB: record_for_bob()}}

    assert hubd.sweep_orphan_queues(tmp_path, recorder, reg) == []
    assert storage.list_queue(tmp_path, "ghost-9")


def test_rename_survives_refresh_sweep_prune_chain(tmp_path, monkeypatch):
    recorder = Recorder()
    renamed = record_for_bob()
    renamed["slot"] = "pi:old"
    renamed["display_name"] = "old"
    reg = {"agents": {BOB: renamed}}
    snapshots = {
        "": {"panes": {"%2": {"pane_pid": "200", "slot": "pi:new", "pane_created": "1"}}, "slots": {"pi:new": "%2"}}
    }

    hubd.refresh_display_names(reg, tmp_path, recorder, snapshots)
    online = hubd.sweep_liveness(reg, tmp_path, recorder, {}, {}, 100.0, snapshots)
    pruned = hubd.prune_registry(reg, tmp_path, recorder, online, 100.0)

    assert online[BOB] is True
    assert pruned == []
    assert reg["agents"][BOB]["slot"] == "pi:new"
    assert any("slot codex-h-2 -> pi:new" in line for line in recorder.lines)


def test_hub_lock_single_flight(tmp_path, monkeypatch):
    monkeypatch.setattr(hubd, "HUB_LOCK_RETRY_SECONDS", 0.2)

    holder = hubd.acquire_hub_lock(tmp_path)
    assert holder is not None
    try:
        assert hubd.acquire_hub_lock(tmp_path) is None
    finally:
        holder.close()

    again = hubd.acquire_hub_lock(tmp_path)
    assert again is not None
    again.close()


def test_respawn_offline_spawners_clears_stale_anchor(tmp_path, monkeypatch):
    recorder = Recorder()
    storage.enqueue(tmp_path, envelope_to_bob())
    dead = record_for_bob(spawn_cmd=["echo"])
    reg = {"agents": {BOB: dead}}
    online = {BOB: False}

    hubd.respawn_offline_spawners(reg, tmp_path, recorder, online)

    assert online[BOB] is True
    assert reg["agents"][BOB]["pane_id"] == ""
    assert any(line.startswith(f"respawn-path {BOB}") for line in recorder.lines)

    idle = record_for_bob(spawn_cmd=["echo"])
    idle["agent_id"] = "codex-idle-9"
    reg_idle = {"agents": {"codex-idle-9": idle}}
    hubd.respawn_offline_spawners(reg_idle, tmp_path, recorder, {"codex-idle-9": False})
    assert reg_idle["agents"]["codex-idle-9"]["pane_id"] == "%2"


def test_reinject_guard_blocks_recent_stamp(tmp_path, monkeypatch):
    recorder = Recorder()
    wire_fake_tmux(monkeypatch, recorder)
    wire_busy_gate(monkeypatch)
    storage.enqueue(tmp_path, envelope_to_bob())
    reg = registry_with_bob(record_for_bob())
    deliveries = {}

    hubd.step(tmp_path, reg, deliveries, recorder, 100.0, {BOB: True})
    hubd.step(tmp_path, reg, deliveries, recorder, 102.0, {BOB: True})
    assert len(recorder.injects) == 1
    assert storage.recently_injected(storage.read_msg(tmp_path, BOB, "m1"), 103.0, hubd.REINJECT_GUARD_SECONDS)

    deliveries.clear()
    hubd.step(tmp_path, reg, deliveries, recorder, 104.0, {BOB: True})
    assert len(recorder.injects) == 1

    stale = storage.read_msg(tmp_path, BOB, "m1")
    stale["last_injected_at"] = 100.0 - hubd.REINJECT_GUARD_SECONDS - 1
    storage.enqueue(tmp_path, stale)
    hubd.step(tmp_path, reg, deliveries, recorder, 110.0, {BOB: True})
    hubd.step(tmp_path, reg, deliveries, recorder, 111.0, {BOB: True})
    assert len(recorder.injects) == 1
    resumed = deliveries[f"{BOB}/m1"]
    assert resumed.state == hubd.STATE_WAIT_CONFIRM
    assert resumed.state_since == stale["last_injected_at"]
    hubd.step(tmp_path, reg, deliveries, recorder, stale["last_injected_at"] + hubd.CONFIRM_PATIENCE_SECONDS + 1, {BOB: True})
    assert resumed.state == hubd.STATE_DONE
    assert (tmp_path / "history" / "m1.json").exists()


def test_refresh_display_names_updates_only_on_change(tmp_path, monkeypatch):
    recorder = Recorder()
    reg = {"agents": {BOB: record_for_bob()}}
    seen = {"slot": "pi:codexwin"}

    def fake_slot(pane, ssh_host=None):
        return seen["slot"]

    monkeypatch.setattr(hubd.tmuxio, "pane_slot", fake_slot)
    hubd.refresh_display_names(reg, tmp_path, recorder)
    stored = tmp_path.joinpath("registry.json")
    assert stored.exists() or reg["agents"][BOB]["display_name"] == "codexwin"
    assert any("slot" in line for line in recorder.lines)

    recorder.lines.clear()
    hubd.refresh_display_names(reg, tmp_path, recorder)
    assert recorder.lines == []

    seen["slot"] = "pi:probe"
    hubd.refresh_display_names(reg, tmp_path, recorder)
    assert reg["agents"][BOB]["display_name"] == "probe"


def test_sweep_uses_snapshot_no_per_agent_queries(tmp_path, monkeypatch):
    recorder = Recorder()
    moved = record_for_bob()
    moved["slot"] = "pi:codex"
    far = record_for_bob(pane_id="%5", pane_pid="500")
    far["agent_id"] = "codex-win-9"
    reg = {"agents": {BOB: moved, "codex-win-9": far}}

    def leak(*args, **kwargs):
        raise AssertionError("快照在场时禁止逐端单查 ssh/tmux")

    monkeypatch.setattr(hubd.tmuxio, "slot_pane_id", leak)
    monkeypatch.setattr(hubd.tmuxio, "pane_pid_matches", leak)
    snap = {
        "": {
            "panes": {
                "%9": {"pane_pid": "900", "slot": "pi:codex", "pane_created": "1", "command": "codex"},
                "%5": {"pane_pid": "500", "slot": "pi:other", "pane_created": "2", "command": "codex"},
            },
            "slots": {"pi:codex": "%9", "pi:other": "%5"},
        }
    }
    online = hubd.sweep_liveness(reg, tmp_path, recorder, {}, {}, 100.0, snap)

    assert online[BOB] is True
    assert online["codex-win-9"] is True
    assert reg["agents"][BOB]["pane_id"] == "%9"
    assert reg["agents"][BOB]["pane_pid"] == "900"
    assert registry.get(tmp_path, BOB)["pane_id"] == "%9"


def test_refresh_display_names_uses_snapshot(tmp_path, monkeypatch):
    recorder = Recorder()
    record = record_for_bob()
    record["slot"] = "pi:old"
    record["display_name"] = "old"
    reg = {"agents": {BOB: record}}

    def leak(*args, **kwargs):
        raise AssertionError("快照在场时禁止逐端单查 ssh/tmux")

    monkeypatch.setattr(hubd.tmuxio, "pane_slot", leak)
    snap = {"": {"panes": {"%2": {"pane_pid": "200", "slot": "pi:renamed", "pane_created": "1"}}, "slots": {"pi:renamed": "%2"}}}
    hubd.refresh_display_names(reg, tmp_path, recorder, snap)

    assert reg["agents"][BOB]["slot"] == "pi:renamed"
    assert reg["agents"][BOB]["display_name"] == "renamed"
    assert registry.get(tmp_path, BOB)["slot"] == "pi:renamed"


def test_step_dirty_scope_scans_only_dirty_agents(tmp_path, monkeypatch):
    recorder = Recorder()
    wire_fake_tmux(monkeypatch, recorder)
    wire_busy_gate(monkeypatch)
    storage.enqueue(tmp_path, envelope_to_bob())
    other = envelope_to_bob(msg_id="m2")
    other["to"] = "codex-win-9"
    storage.enqueue(tmp_path, other)
    reg = {
        "agents": {
            BOB: record_for_bob(),
            "codex-win-9": record_for_bob(pane_id="%5", pane_pid="500"),
        }
    }
    deliveries = {}
    scanned = []
    original_list = storage.list_queue

    def counting_list(root, agent_id, on_unreadable=None):
        scanned.append(agent_id)
        return original_list(root, agent_id)

    monkeypatch.setattr(hubd.storage, "list_queue", counting_list)
    hubd.step(tmp_path, reg, deliveries, recorder, 100.0, {BOB: True}, dirty_agents={BOB})

    assert scanned == [BOB]
    assert f"{BOB}/m1" in deliveries
    assert "codex-win-9/m2" not in deliveries


def test_step_frame_cache_shared_per_pane(tmp_path, monkeypatch):
    recorder = Recorder()
    wire_fake_tmux(monkeypatch, recorder)
    wire_busy_gate(monkeypatch)
    storage.enqueue(tmp_path, envelope_to_bob(msg_id="m1"))
    second = envelope_to_bob(msg_id="m2")
    second["to"] = "pi-two"
    second["ack_id"] = "ack-m2"
    storage.enqueue(tmp_path, second)
    reg = {"agents": {BOB: record_for_bob(), "pi-two": record_for_bob()}}
    online = {BOB: True, "pi-two": True}
    deliveries = {}
    captures = {"count": 0}
    original = hubd.tmuxio.capture_joined_bottom

    def counting_capture(pane, line_count=60, ssh_host=None):
        captures["count"] += 1
        return original(pane, line_count, ssh_host)

    monkeypatch.setattr(hubd.tmuxio, "capture_joined_bottom", counting_capture)
    hubd.step(tmp_path, reg, deliveries, recorder, 100.0, online)
    frames = {}
    hubd.step(tmp_path, reg, deliveries, recorder, 102.0, online, frame_cache=frames)
    recorder.echo_msg_ids.update({"m1", "m2"})
    hubd.step(tmp_path, reg, deliveries, recorder, 103.0, online, frame_cache=frames)
    hubd.step(tmp_path, reg, deliveries, recorder, 105.0, online, frame_cache=frames)
    hubd.step(tmp_path, reg, deliveries, recorder, 106.0, online, frame_cache=frames)

    assert deliveries[f"{BOB}/m1"].state == hubd.STATE_WAIT_CONFIRM
    assert deliveries["pi-two/m2"].state == hubd.STATE_WAIT_CONFIRM
    assert captures["count"] <= 4


def test_injecting_churn_blocks_enter_promotion(tmp_path, monkeypatch):
    recorder = Recorder()
    wire_fake_tmux(monkeypatch, recorder)
    wire_busy_gate(monkeypatch)
    delivery = hubd.Delivery(envelope_to_bob(), now=100.0, pane_id="%2")
    frames = {}
    enters = []
    monkeypatch.setattr(hubd.tmuxio, "send_enter", lambda pane, ssh=None: enters.append(pane))

    delivery.tick(tmp_path, recorder, 102.0, True, frames)
    assert delivery.state == hubd.STATE_INJECTING

    delivery.enter_tail = "line1\nline2\ntyping draft"
    growth = {"on": True, "n": 0}
    original_capture = hubd.tmuxio.capture_joined_bottom

    def churning_capture(pane, line_count=60, ssh_host=None):
        if growth["on"]:
            growth["n"] += 1
            return "line1\nline2\ntyping draft" + "x" * growth["n"]
        return original_capture(pane, line_count, ssh_host)

    monkeypatch.setattr(hubd.tmuxio, "capture_joined_bottom", churning_capture)
    for moment in (103.0, 105.0, 110.0, 120.0):
        frames.clear()
        delivery.tick(tmp_path, recorder, moment, True, frames)
    assert delivery.state == hubd.STATE_INJECTING
    assert enters == []

    growth["on"] = False
    frames.clear()
    delivery.tick(tmp_path, recorder, 121.0, True, frames)
    frames.clear()
    delivery.tick(tmp_path, recorder, 122.0, True, frames)
    frames.clear()
    delivery.tick(tmp_path, recorder, 125.0, True, frames)
    assert enters == ["%2", "%2"]
    assert delivery.state == hubd.STATE_WAIT_CONFIRM


def test_injecting_patience_settles_confirm_never_fails(tmp_path, monkeypatch):
    recorder = Recorder()
    wire_fake_tmux(monkeypatch, recorder)
    wire_busy_gate(monkeypatch)
    storage.enqueue(tmp_path, envelope_to_bob())
    delivery = hubd.Delivery(envelope_to_bob(), now=100.0, pane_id="%2")
    frames = {}
    delivery.tick(tmp_path, recorder, 102.0, True, frames)
    delivery.tick(tmp_path, recorder, 103.0, True, frames)
    growth = {"n": 0}
    original_capture = hubd.tmuxio.capture_joined_bottom

    def churning_capture(pane, line_count=60, ssh_host=None):
        if growth.get("still"):
            return "line1\nline2\ntyping draft final"
        growth["n"] += 1
        return f"line1\nline2\ntyping draft {growth['n']}"

    monkeypatch.setattr(hubd.tmuxio, "capture_joined_bottom", churning_capture)
    frames.clear()
    delivery.tick(tmp_path, recorder, 200.0, True, frames)
    assert delivery.state == hubd.STATE_INJECTING

    growth["still"] = True
    frames.clear()
    delivery.tick(tmp_path, recorder, 200.0, True, frames)
    assert delivery.state == hubd.STATE_WAIT_CONFIRM
    assert any("via=enter-ladder" in line for line in recorder.lines)
    assert not any("FAILED" in line for line in recorder.lines)
    assert not (storage.queue_dir(tmp_path, BOB) / "m1.failed").exists()


def test_same_pane_second_delivery_defers_during_injection(tmp_path, monkeypatch):
    recorder = Recorder()
    recorder.echo_msg_ids = set()
    wire_fake_tmux(monkeypatch, recorder)
    wire_busy_gate(monkeypatch)
    storage.enqueue(tmp_path, envelope_to_bob(msg_id="m1"))
    second = envelope_to_bob(msg_id="m2")
    second["ack_id"] = "ack-m2"
    storage.enqueue(tmp_path, second)
    reg = registry_with_bob(record_for_bob())
    deliveries = {}
    online = {BOB: True}

    hubd.step(tmp_path, reg, deliveries, recorder, 100.0, online)
    hubd.step(tmp_path, reg, deliveries, recorder, 102.0, online)

    assert deliveries[f"{BOB}/m1"].state == hubd.STATE_INJECTING
    assert deliveries[f"{BOB}/m2"].state == hubd.STATE_INJECTING or (
        deliveries[f"{BOB}/m2"].deferred >= 0
    )
    primes = [text for _, text, _ in recorder.injects]
    assert len(recorder.injects) == 2


def test_reanchor_cwd_panes_unique_hit(tmp_path, monkeypatch):
    recorder = Recorder()
    reg = registry_with_bob(record_for_bob())
    reg["agents"]["codex-h-9-ghost"] = {
        "agent_id": "codex-h-9-ghost", "cli": "codex", "host": "localhost",
        "pane_id": "", "pane_pid": "", "slot": "", "cwd": "/mnt/d/000-project", "spawn_cmd": None,
    }
    snapshots = {"": {"panes": {
        "%2": {"pane_pid": "200", "slot": "pi:codex", "pane_created": "0", "cwd": "/tmp", "command": "codex"},
        "%9": {"pane_pid": "999", "slot": "zero:codexmaster", "pane_created": "0", "cwd": "/mnt/d/000-project", "command": "codex"},
    }, "slots": {}}}
    hubd.reanchor_cwd_panes(reg, tmp_path, recorder, snapshots)
    ghost = registry.load(tmp_path)["agents"]["codex-h-9-ghost"]
    assert ghost["pane_id"] == "%9"
    assert ghost["pane_pid"] == "999"
    assert ghost["slot"] == "zero:codexmaster"
    assert ghost["display_name"] == "codexmaster"
    assert any("re-anchored codex-h-9-ghost -> pane %9" in line for line in recorder.lines)

    ambiguous = dict(snapshots)
    ambiguous[""] = {"panes": {
        "%9": {"pane_pid": "999", "slot": "zero:codexmaster", "pane_created": "0", "cwd": "/mnt/d/000-project", "command": "codex"},
        "%8": {"pane_pid": "888", "slot": "zero:other", "pane_created": "0", "cwd": "/mnt/d/000-project", "command": "codex"},
    }, "slots": {}}
    reg["agents"]["codex-h-9-ghost"] = dict(reg["agents"]["codex-h-9-ghost"], pane_id="", pane_pid="", slot="")
    hubd.reanchor_cwd_panes(reg, tmp_path, recorder, ambiguous)
    assert reg["agents"]["codex-h-9-ghost"]["pane_id"] == ""
    assert len([line for line in recorder.lines if "re-anchored" in line]) == 1


def test_reanchor_cwd_panes_rejects_foreign_cli(tmp_path):
    recorder = Recorder()
    reg = registry_with_bob(record_for_bob())
    for agent_id, cli in (("unknown-h-9-ghost", "unknown"), ("claude-h-9-twin", "claude")):
        reg["agents"][agent_id] = {
            "agent_id": agent_id, "cli": cli, "host": "localhost",
            "pane_id": "", "pane_pid": "", "slot": "", "cwd": "/mnt/d/000-project", "spawn_cmd": None,
        }
    snapshots = {"": {"panes": {
        "%9": {"pane_pid": "999", "slot": "zero:codexmaster", "pane_created": "0", "cwd": "/mnt/d/000-project", "command": "codex"},
    }, "slots": {}}}
    hubd.reanchor_cwd_panes(reg, tmp_path, recorder, snapshots)
    assert reg["agents"]["unknown-h-9-ghost"]["pane_id"] == ""
    assert reg["agents"]["claude-h-9-twin"]["pane_id"] == ""
    assert not any("re-anchored" in line for line in recorder.lines)


def test_offline_stalled_mail_bounces(tmp_path, monkeypatch):
    recorder = Recorder()
    ghost = {"agent_id": "unknown-h-9-ghost", "cli": "unknown", "host": "localhost",
             "pane_id": "", "pane_pid": "", "slot": "", "spawn_cmd": None}
    reg = registry_with_bob(record_for_bob())
    reg["agents"]["unknown-h-9-ghost"] = ghost
    stale = envelope_to_bob(msg_id="stalled01", body="回函")
    stale["to"] = "unknown-h-9-ghost"
    stale["from"] = BOB
    stale["created_at"] = 1.0
    storage.enqueue(tmp_path, stale)
    fresh = envelope_to_bob(msg_id="fresh000001", body="新消息")
    fresh["to"] = "unknown-h-9-ghost"
    fresh["from"] = BOB
    fresh["created_at"] = 10_000.0 + hubd.OFFLINE_STALL_SECONDS
    storage.enqueue(tmp_path, fresh)

    deliveries: dict = {}
    hubd.sweep_offline_stalled(tmp_path, recorder, reg, {}, 10_000.0 + hubd.OFFLINE_STALL_SECONDS + 1.0, deliveries)

    assert (storage.queue_dir(tmp_path, "unknown-h-9-ghost") / "stalled01.failed").exists()
    assert storage.read_msg(tmp_path, "unknown-h-9-ghost", "fresh000001") is not None
    assert any("delivery-stalled stalled01" in line for line in recorder.lines)
    bounce_files = list((storage.queue_dir(tmp_path, BOB)).glob("*.msg"))
    assert any("stalled01" in path.read_text() and json.loads(path.read_text()).get("bounce") for path in bounce_files)


def test_tail_marker_pending_settles_confirm_no_refail_no_reinject(tmp_path, monkeypatch):
    recorder = Recorder()
    wire_fake_tmux(monkeypatch, recorder)
    wire_busy_gate(monkeypatch)
    storage.enqueue(tmp_path, envelope_to_bob())
    delivery = hubd.Delivery(envelope_to_bob(), now=100.0, pane_id="%2")
    frames = {}
    delivery.tick(tmp_path, recorder, 102.0, True, frames)
    frames.clear()
    assert delivery.state == hubd.STATE_INJECTING

    clock = {"t": 0, "churn": True}

    def churning_then_pending_capture(pane, line_count=60, ssh_host=None):
        if clock["churn"]:
            clock["t"] += 1
            return "\n".join(
                [f"history line {n}" for n in range(20)]
                + ["input box"] * 8
                + ["", "queued [A2A] from=claude-h-1 id=m1 rest" + "·" * clock["t"]]
            )
        return "\n".join(
            [f"history line {n}" for n in range(20)]
            + ["input box"] * 8
            + ["", "queued [A2A] from=claude-h-1 id=m1 rest of text"]
        )

    monkeypatch.setattr(hubd.tmuxio, "capture_joined_bottom", churning_then_pending_capture)
    for moment in (103.0, 110.0, 150.0, 200.0):
        frames.clear()
        delivery.tick(tmp_path, recorder, moment, True, frames)
    assert delivery.state == hubd.STATE_INJECTING

    clock["churn"] = False
    frames.clear()
    delivery.tick(tmp_path, recorder, 201.0, True, frames)
    assert delivery.state == hubd.STATE_WAIT_CONFIRM
    assert any("via=tail-echo" in line for line in recorder.lines)
    assert len(recorder.injects) == 1
    assert not any("FAILED" in line for line in recorder.lines)

    frames.clear()
    delivery.tick(
        tmp_path,
        recorder,
        201.0 + hubd.CONFIRM_PATIENCE_SECONDS + 10.0,
        True,
        frames,
    )
    assert delivery.state == hubd.STATE_DONE
    assert not (storage.queue_dir(tmp_path, "codex-h-2") / "m1.failed").exists()
    assert (tmp_path / "history" / "m1.json").exists()
    assert not any("bounce" in line for line in recorder.lines)


def test_dirty_envelope_fails_marked_without_killing_round(tmp_path, monkeypatch):
    recorder = Recorder()
    wire_fake_tmux(monkeypatch, recorder)
    wire_busy_gate(monkeypatch)
    dirty = envelope_to_bob()
    dirty["last_injected_at"] = "not-a-float"
    storage.enqueue(tmp_path, dirty)
    clean = envelope_to_bob(msg_id="m2")
    storage.enqueue(tmp_path, clean)
    reg = registry_with_bob(record_for_bob())
    deliveries = {}

    hubd.step(tmp_path, reg, deliveries, recorder, 100.0, {BOB: True})
    hubd.step(tmp_path, reg, deliveries, recorder, 102.0, {BOB: True})

    assert (storage.queue_dir(tmp_path, BOB) / "m1.failed").exists()
    assert any(line.startswith("envelope-error codex-h-2/m1") for line in recorder.lines)
    assert f"{BOB}/m2" in deliveries


def test_malformed_notify_json_warns_once(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    (tmp_path / "notify.json").write_text("{broken")
    hubd.NOTIFY_CONFIG_WARNED = False
    recorder = Recorder()

    assert REAL_LOAD_NOTIFY(recorder) == []
    assert REAL_LOAD_NOTIFY(recorder) == []
    warn_lines = [line for line in recorder.lines if "notify.json" in line]
    assert len(warn_lines) == 1


def test_registry_corruption_invokes_callback(tmp_path):
    from common import registry as registry_module

    (tmp_path / "registry.json").write_text("{corrupt")
    warned = []
    loaded = registry_module.load(tmp_path, on_corrupt=lambda exc: warned.append(exc))
    assert loaded["agents"] == {}
    assert warned and isinstance(warned[0], ValueError)
    assert registry_module.load(tmp_path, on_corrupt=lambda exc: warned.append(exc))["agents"] == {}


def test_rate_storm_observed_with_edge_notify(tmp_path, monkeypatch):
    recorder = Recorder()
    monkeypatch.setattr(hubd, "load_notify_cmd", lambda log=None: ["toast"])
    pool = RecordingPool()
    monkeypatch.setattr(hubd, "NOTIFY_POOL", pool)
    for index in range(storage.RATE_MAX_PER_WINDOW + 2):
        storage.rate_gate(tmp_path, "claude-h-1", "codex-h-2", now=time.time())

    storms = hubd.sweep_rate_storms(tmp_path, recorder, set())
    assert any(line.startswith(f"rate-storm {storage.pair_key('claude-h-1', BOB)}") for line in recorder.lines)
    assert [json.loads(payload)["event"] for _, payload, _ in pool.spawned] == ["rate-storm"]

    storms = hubd.sweep_rate_storms(tmp_path, recorder, storms)
    assert [json.loads(payload)["event"] for _, payload, _ in pool.spawned] == ["rate-storm"]


def pi_record_for_bob(pane_id="%2"):
    record = record_for_bob(pane_id=pane_id)
    record["cli"] = "pi"
    return record


def run_step(tmp_path, recorder, deliveries, now, cli_record=None):
    reg = {"agents": {BOB: cli_record or pi_record_for_bob()}}
    hubd.step(tmp_path, reg, deliveries, recorder, now, {BOB: True})
    return deliveries.get(f"{BOB}/m1")


def test_native_dispatch_ack_roundtrip(tmp_path, monkeypatch):
    from common import nativebox

    recorder = Recorder()
    monkeypatch.setattr(hubd.tmuxio, "prime_injection", recorder.fake_inject)
    monkeypatch.setattr(hubd.tmuxio, "pane_created", lambda pane, ssh=None: 0.0)
    paths.ensure_layout(tmp_path)
    storage.enqueue(tmp_path, envelope_to_bob())
    start = time.time()
    nativebox.write_alive(tmp_path, BOB, 4321, start)

    delivery = run_step(tmp_path, recorder, {}, start)
    assert delivery is not None and delivery.state == hubd.STATE_WAIT_CONFIRM
    assert recorder.injects == []
    assert any("injected m1 via=pi-native" in line and "入队即送达" in line for line in recorder.lines)
    assert float(storage.read_msg(tmp_path, BOB, "m1")["last_injected_at"]) == start

    delivery.tick(tmp_path, recorder, start + 4.0, True, None)
    assert delivery.state == hubd.STATE_WAIT_CONFIRM

    storage.write_ack(tmp_path, "ack-m1", "claude-h-1")
    delivery.tick(tmp_path, recorder, start + 6.0, True, None)
    assert delivery.state == hubd.STATE_DONE
    assert not (tmp_path / "queue" / BOB / "m1.msg").exists()
    assert recorder.injects == []


def test_native_unconsumed_settles_unconfirmed_never_degrades(tmp_path, monkeypatch):
    from common import nativebox

    recorder = Recorder()
    monkeypatch.setattr(hubd.tmuxio, "prime_injection", recorder.fake_inject)
    monkeypatch.setattr(hubd, "CONFIRM_PATIENCE_SECONDS", 5.0)
    paths.ensure_layout(tmp_path)
    storage.enqueue(tmp_path, envelope_to_bob())
    start = time.time()
    nativebox.write_alive(tmp_path, BOB, 4321, start)

    delivery = run_step(tmp_path, recorder, {}, start)
    assert delivery.state == hubd.STATE_WAIT_CONFIRM

    busy = start + 3.0
    delivery.tick(tmp_path, recorder, busy, True, None)
    assert delivery.state == hubd.STATE_WAIT_CONFIRM and delivery.native
    delivery.tick(tmp_path, recorder, busy + hubd.CONFIRM_PATIENCE_SECONDS + 1.0, True, None)
    assert delivery.state == hubd.STATE_DONE
    assert (tmp_path / "history" / "m1.json").exists()
    assert not (tmp_path / "queue" / BOB / "m1.failed").exists()
    assert recorder.injects == []
    assert not any("degraded" in line or "FAILED" in line for line in recorder.lines)


def test_native_resume_after_hub_restart(tmp_path, monkeypatch):
    from common import nativebox

    recorder = Recorder()
    monkeypatch.setattr(hubd.tmuxio, "prime_injection", recorder.fake_inject)
    monkeypatch.setattr(hubd.tmuxio, "pane_created", lambda pane, ssh=None: 0.0)
    paths.ensure_layout(tmp_path)
    storage.enqueue(tmp_path, envelope_to_bob())
    start = time.time()
    nativebox.write_alive(tmp_path, BOB, 4321, start)

    delivery = run_step(tmp_path, recorder, {}, start)
    assert delivery.state == hubd.STATE_WAIT_CONFIRM

    restart = start + hubd.REINJECT_GUARD_SECONDS + 10.0
    nativebox.write_alive(tmp_path, BOB, 4321, restart)
    deliveries = {}
    resumed = run_step(tmp_path, recorder, deliveries, restart)
    assert resumed.state == hubd.STATE_WAIT_CONFIRM
    dispatch_lines = [line for line in recorder.lines if "via=pi-native" in line and "injected" in line]
    assert len(dispatch_lines) == 1
    assert recorder.injects == []

    deliveries = {}
    confirmed = run_step(tmp_path, recorder, deliveries, restart + 4.0)
    assert confirmed.state == hubd.STATE_WAIT_CONFIRM
    assert recorder.injects == []


def test_step_scan_skips_online_pull_only_recipient(tmp_path, monkeypatch):
    recorder = Recorder()
    wire_fake_tmux(monkeypatch, recorder)
    storage.enqueue(tmp_path, envelope_to_bob())
    reg = {"agents": {BOB: {**record_for_bob(), "cli": "zcode", "pane_id": "", "spawn_cmd": None}}}

    hubd.step(tmp_path, reg, {}, recorder, 100.0, {BOB: True})

    assert storage.read_msg(tmp_path, BOB, "m1") is not None
    assert recorder.injects == []
    assert not any("FAILED" in line or "bounce" in line for line in recorder.lines)


def test_pull_only_recipient_keeps_queue_on_stall(tmp_path):
    recorder = Recorder()
    paths.ensure_layout(tmp_path)
    storage.enqueue(tmp_path, envelope_to_bob())
    reg = {"agents": {BOB: {**record_for_bob(), "cli": "zcode", "pane_id": "", "spawn_cmd": None}}}
    hubd.sweep_offline_stalled(tmp_path, recorder, reg, {BOB: False}, 8000.0, {})
    assert storage.read_msg(tmp_path, BOB, "m1") is not None
    assert not (tmp_path / "queue" / "claude-h-1" / "m1.msg").exists()
    assert any("保留队列待 mail_poll 拉取" in line for line in recorder.lines)
    notified_at = float(storage.read_msg(tmp_path, BOB, "m1")["stall_notified_at"])
    hubd.sweep_offline_stalled(tmp_path, recorder, reg, {BOB: False}, 9000.0, {})
    assert float(storage.read_msg(tmp_path, BOB, "m1")["stall_notified_at"]) == notified_at
    assert len([line for line in recorder.lines if "delivery-stalled" in line]) == 1


def test_non_pull_offline_still_bounces(tmp_path):
    recorder = Recorder()
    paths.ensure_layout(tmp_path)
    storage.enqueue(tmp_path, envelope_to_bob())
    reg = {"agents": {BOB: {**record_for_bob(), "pane_id": "", "spawn_cmd": None}}}
    hubd.sweep_offline_stalled(tmp_path, recorder, reg, {BOB: False}, 8000.0, {})
    assert storage.read_msg(tmp_path, BOB, "m1") is None
    assert (tmp_path / "queue" / "claude-h-1").exists()
    assert any("回弹发送方" in line for line in recorder.lines)


def codex_record(pane_id="%7", **extra):
    record = {
        "agent_id": BOB,
        "cli": "codex",
        "host": "localhost",
        "pane_id": pane_id,
        "pane_pid": "700",
        "cwd": "/tmp",
        "spawn_cmd": None,
        "codex_bin": "/usr/local/bin/codex",
        "codex_home": "/tmp/fake-codex-home",
        "codex_thread": "aaaa5c8b-07a4-7f61-a73c-312c7a2d915e",
    }
    record.update(extra)
    return record


def run_codex_step(tmp_path, recorder, deliveries, now, record=None):
    reg = {"agents": {BOB: record or codex_record()}}
    hubd.step(tmp_path, reg, deliveries, recorder, now, {BOB: True})
    return deliveries.get(f"{BOB}/m1")


def test_queue_dispatch_reanchors_switched_session_thread(tmp_path, monkeypatch):
    recorder = Recorder()
    monkeypatch.setattr(hubd.tmuxio, "prime_injection", recorder.fake_inject)
    monkeypatch.setattr(hubd.tmuxio, "pane_created", lambda pane, ssh=None: 0.0)
    monkeypatch.setattr(hubd.codexq, "daemon_alive", lambda home: True)
    stale = codex_record(codex_thread="01a15887-ec89-7df1-99aa-50888f2246a9", cwd="/mnt/d/000-project", pane_id="")
    registry.upsert(tmp_path, BOB, stale)
    fresh_thread = "01a1a999-aaaa-bbbb-cccc-dddddddddddd"
    monkeypatch.setattr(
        hubd.codexq, "locate_win", lambda cwd: {"codex_thread": fresh_thread, "codex_bin": stale["codex_bin"], "codex_home": stale["codex_home"]}
    )
    threads = []

    def fake_enqueue(codex_bin, codex_home, thread_id, message):
        threads.append(thread_id)
        return None, ""

    monkeypatch.setattr(hubd.codexq, "enqueue_async", fake_enqueue)
    paths.ensure_layout(tmp_path)
    storage.enqueue(tmp_path, envelope_to_bob("m1"))
    delivery = run_codex_step(tmp_path, recorder, {}, time.time(), record=stale)
    assert threads == [fresh_thread]
    assert registry.load(tmp_path)["agents"][BOB]["codex_thread"] == fresh_thread
    assert any("queue-thread-reanchored" in line for line in recorder.lines)
    assert delivery is None or delivery.state == hubd.STATE_WAIT_NATIVE


def test_queue_daemon_dispatch_receipt_ack(tmp_path, monkeypatch):
    from common import codexq, nativebox

    recorder = Recorder()
    monkeypatch.setattr(hubd.tmuxio, "prime_injection", recorder.fake_inject)
    monkeypatch.setattr(hubd.tmuxio, "pane_created", lambda pane, ssh=None: 0.0)
    monkeypatch.setattr(hubd.codexq, "daemon_alive", lambda home: True)
    started = {"proc": None}

    class FakeProc:
        def __init__(self, output):
            self.output = output
            self._done = False

        def poll(self):
            return 0 if self._done else None

        def finish(self):
            Path(self.outpath).write_text(self.output)
            self._done = True

    def fake_enqueue(codex_bin, codex_home, thread_id, message):
        proc = FakeProc("Queued message 01a1a602-754b-7c01-b965-9865d627bbd0 for thread x\n")
        proc.outpath = "/tmp/a2a-test-q.out"
        Path(proc.outpath).write_text("")
        started["proc"] = proc
        return proc, proc.outpath

    monkeypatch.setattr(hubd.codexq, "enqueue_async", fake_enqueue)
    paths.ensure_layout(tmp_path)
    storage.enqueue(tmp_path, envelope_to_bob("m1"))
    start = time.time()

    delivery = run_codex_step(tmp_path, recorder, {}, start)
    assert delivery is not None and delivery.state == hubd.STATE_WAIT_NATIVE
    assert delivery.queue_proc is not None
    assert recorder.injects == []

    delivery.tick(tmp_path, recorder, start + 0.5, True, None)
    assert delivery.state == hubd.STATE_WAIT_NATIVE
    started["proc"].finish()
    delivery.tick(tmp_path, recorder, start + 1.0, True, None)
    assert delivery.state == hubd.STATE_WAIT_CONFIRM
    assert any("via=codex-queue" in line and "queued=01a1a602" in line for line in recorder.lines)
    assert nativebox.rcpt_exists(tmp_path, BOB, "m1")

    storage.write_ack(tmp_path, "ack-m1", "sender")
    delivery.tick(tmp_path, recorder, start + 2.0, True, None)
    assert delivery.state == hubd.STATE_DONE
    assert recorder.injects == []


def test_queue_daemon_failure_retries_never_degrades_to_tmux(tmp_path, monkeypatch):
    recorder = Recorder()
    monkeypatch.setattr(hubd.tmuxio, "prime_injection", recorder.fake_inject)
    monkeypatch.setattr(hubd.tmuxio, "pane_created", lambda pane, ssh=None: 0.0)
    monkeypatch.setattr(hubd.codexq, "daemon_alive", lambda home: True)

    class DeadProc:
        def poll(self):
            return 1

    monkeypatch.setattr(hubd.codexq, "enqueue_async", lambda *a, **k: (DeadProc(), "/tmp/a2a-dead.out"))
    paths.ensure_layout(tmp_path)
    storage.enqueue(tmp_path, envelope_to_bob("m1"))
    start = time.time()
    deliveries = {}

    delivery = run_codex_step(tmp_path, recorder, deliveries, start)
    assert delivery is None
    assert deliveries == {}
    stamped = storage.read_msg(tmp_path, BOB, "m1")
    assert stamped["queue_attempts"] == 1
    assert stamped["queue_retry_not_before"] == start + hubd.QUEUE_RETRY_DELAY_SECONDS
    assert stamped["last_injected_at"] == 0
    assert any("queue-retry" in line and "不降级 tmux" in line for line in recorder.lines)

    run_codex_step(tmp_path, recorder, deliveries, start + 10.0)
    assert deliveries == {} and recorder.injects == []
    assert storage.read_msg(tmp_path, BOB, "m1")["queue_attempts"] == 1

    run_codex_step(tmp_path, recorder, deliveries, start + hubd.QUEUE_RETRY_DELAY_SECONDS + 1.0)
    assert storage.read_msg(tmp_path, BOB, "m1")["queue_attempts"] == 2

    run_codex_step(tmp_path, recorder, deliveries, start + 2 * hubd.QUEUE_RETRY_DELAY_SECONDS + 2.0)
    assert (tmp_path / "queue" / BOB / "m1.failed").exists()
    assert storage.read_msg(tmp_path, BOB, "m1") is None
    assert any("FAILED" in line and "queue" in line for line in recorder.lines)
    bounce_dir = tmp_path / "queue" / "claude-h-1"
    assert bounce_dir.is_dir() and len(list(bounce_dir.glob("*.msg"))) == 1
    assert recorder.injects == []


def test_queue_daemon_unreadable_receipt_assumes_accepted(tmp_path, monkeypatch):
    from common import nativebox

    recorder = Recorder()
    monkeypatch.setattr(hubd.tmuxio, "prime_injection", recorder.fake_inject)
    monkeypatch.setattr(hubd.codexq, "daemon_alive", lambda home: True)

    class SilentProc:
        def poll(self):
            return 0

    monkeypatch.setattr(hubd.codexq, "enqueue_async", lambda *a, **k: (SilentProc(), "/tmp/a2a-silent.out"))
    monkeypatch.setattr(hubd.codexq, "read_output", lambda path: "")
    paths.ensure_layout(tmp_path)
    storage.enqueue(tmp_path, envelope_to_bob("m1"))
    start = time.time()

    delivery = run_codex_step(tmp_path, recorder, {}, start)
    assert delivery.state == hubd.STATE_WAIT_CONFIRM
    assert nativebox.rcpt_exists(tmp_path, BOB, "m1")
    assert any("receipt-assumed" in line for line in recorder.lines)
    assert recorder.injects == []


def test_queue_daemon_restart_resumes_receipted_not_degraded(tmp_path, monkeypatch):
    from common import nativebox

    recorder = Recorder()
    monkeypatch.setattr(hubd.tmuxio, "prime_injection", recorder.fake_inject)

    def forbid_enqueue(*args, **kwargs):
        raise AssertionError("restart resume 不得重新 dispatch queue 命令")

    monkeypatch.setattr(hubd.codexq, "enqueue_async", forbid_enqueue)
    monkeypatch.setattr(hubd.codexq, "daemon_alive", lambda home: True)
    paths.ensure_layout(tmp_path)
    envelope = envelope_to_bob("m1", expect_reply=True)
    storage.enqueue(tmp_path, envelope)
    crash_at = time.time() - hubd.REINJECT_GUARD_SECONDS - 1.0
    storage.stamp_injected(tmp_path, BOB, "m1", crash_at)
    start = time.time()

    delivery = run_codex_step(tmp_path, recorder, {}, start)
    assert delivery.state == hubd.STATE_WAIT_CONFIRM
    assert delivery.queue_proc is None
    assert recorder.injects == []


def test_queue_daemon_dead_falls_back_to_tmux_build(tmp_path, monkeypatch):
    recorder = Recorder()
    monkeypatch.setattr(hubd.tmuxio, "prime_injection", recorder.fake_inject)
    monkeypatch.setattr(hubd.tmuxio, "quiet_mark", lambda pane, ssh=None: "0")
    monkeypatch.setattr(hubd.tmuxio, "pane_created", lambda pane, ssh=None: 0.0)
    monkeypatch.setattr(hubd.codexq, "daemon_alive", lambda home: False)
    paths.ensure_layout(tmp_path)
    storage.enqueue(tmp_path, envelope_to_bob("m1"))
    start = time.time()

    delivery = run_codex_step(tmp_path, recorder, {}, start)
    assert delivery is not None and delivery.native is False
    delivery.tick(tmp_path, recorder, start + hubd.SETTLE_SECONDS + 0.2, True, None)
    assert delivery.state == hubd.STATE_INJECTING
    assert len(recorder.injects) == 1


WIN_EXE = "/mnt/c/Users/winuser/AppData/Local/OpenAI/Codex/bin/0a1b2c3d4e5f6071/codex.exe"


class FakeDoneProc:
    def __init__(self, output):
        self.output = output

    def poll(self):
        return 0


def write_out(tmp_path, output):
    path = tmp_path / "q-win.out"
    path.write_text(output)
    return str(path)


def windows_record():
    return codex_record(pane_id="", pane_pid="", codex_bin=WIN_EXE)


def test_unknown_cli_with_complete_anchors_builds_queue(tmp_path, monkeypatch):
    recorder = Recorder()
    monkeypatch.setattr(hubd.tmuxio, "prime_injection", recorder.fake_inject)
    monkeypatch.setattr(hubd.codexq, "daemon_alive", lambda home: False)

    def fake_enqueue(codex_bin, codex_home, thread_id, message):
        proc = FakeDoneProc("Queued message 01a1a602-754b-7c01-b965-9865d627bbd0 for thread x\n")
        return proc, write_out(tmp_path, proc.output)

    monkeypatch.setattr(hubd.codexq, "enqueue_async", fake_enqueue)
    bridge_record = windows_record()
    bridge_record["cli"] = "unknown"
    paths.ensure_layout(tmp_path)
    storage.enqueue(tmp_path, envelope_to_bob("m1"))
    start = time.time()

    delivery = run_codex_step(tmp_path, recorder, {}, start, record=bridge_record)
    assert delivery is not None and delivery.queue_daemon is True and delivery.native is True
    assert recorder.injects == []


def test_windows_queue_anchor_dispatches_paneless(tmp_path, monkeypatch):
    from common import nativebox

    recorder = Recorder()
    monkeypatch.setattr(hubd.tmuxio, "prime_injection", recorder.fake_inject)
    monkeypatch.setattr(hubd.codexq, "daemon_alive", lambda home: False)
    dispatched = []

    def fake_enqueue(codex_bin, codex_home, thread_id, message):
        dispatched.append((codex_bin, codex_home, thread_id))
        proc = FakeDoneProc("Queued message 01a1a602-754b-7c01-b965-9865d627bbd0 for thread x\n")
        return proc, write_out(tmp_path, proc.output)

    monkeypatch.setattr(hubd.codexq, "enqueue_async", fake_enqueue)
    paths.ensure_layout(tmp_path)
    storage.enqueue(tmp_path, envelope_to_bob("m1"))
    start = time.time()

    delivery = run_codex_step(tmp_path, recorder, {}, start, record=windows_record())
    assert delivery is not None and delivery.queue_daemon and delivery.state == hubd.STATE_WAIT_CONFIRM
    assert recorder.injects == []
    assert dispatched and dispatched[0][0] == WIN_EXE
    assert nativebox.rcpt_exists(tmp_path, BOB, "m1")


def test_windows_queue_anchor_ensure_online(tmp_path):
    online = {}
    assert hubd.ensure_online(windows_record(), online, {}, time.time()) is True
    assert online[BOB] is True
    online2 = {}
    bare = codex_record(pane_id="", pane_pid="", codex_bin="")
    assert hubd.ensure_online(bare, online2, {}, time.time()) is False
    online3 = {}
    spawner = codex_record(pane_id="", pane_pid="", codex_bin="", spawn_cmd=["codex"])
    assert hubd.ensure_online(spawner, online3, {}, time.time()) is True


def test_windows_queue_anchor_exempt_from_prune(tmp_path, monkeypatch):
    recorder = Recorder()
    stale = time.time() - hubd.REGISTRY_PRUNE_TTL - 60.0
    anchored = windows_record()
    anchored["last_seen"] = stale
    bare = codex_record(pane_id="", pane_pid="", codex_bin="", last_seen=stale)
    reg = {"agents": {BOB: anchored, "bare-1": bare}}
    monkeypatch.setattr(hubd.registry, "forget", lambda root, agent_id: reg["agents"].pop(agent_id, None))
    hubd.prune_registry(reg, tmp_path, recorder, {BOB: True, "bare-1": False}, time.time())
    assert BOB in reg["agents"] and "bare-1" not in reg["agents"]


def test_reanchor_codex_threads_refreshes_stale_thread(tmp_path, monkeypatch):
    recorder = Recorder()
    fresh_thread = "01a1b999-07a4-7f61-a73c-312c7a2d915e"
    monkeypatch.setattr(hubd.codexq, "thread_of_pid", lambda pid: fresh_thread if pid == 700 else "")
    reg = {"agents": {BOB: codex_record()}}
    hubd.reanchor_codex_threads(reg, tmp_path, recorder)
    assert reg["agents"][BOB]["codex_thread"] == fresh_thread
    assert any("codex-thread-reanchored" in line for line in recorder.lines)


def test_settle_archives_receipted_native_mail_instead_of_bounce(tmp_path, monkeypatch):
    from common import nativebox

    recorder = Recorder()
    monkeypatch.setattr(hubd, "enqueue_bounce", lambda root, log, envelope, reason: recorder.write(f"bounce {envelope.get('msg_id')}"))
    paths.ensure_layout(tmp_path)
    storage.enqueue(tmp_path, envelope_to_bob("m1"))
    storage.enqueue(tmp_path, envelope_to_bob("m2"))
    nativebox.write_rcpt(tmp_path, BOB, "m1", time.time())
    settled = hubd.settle_agent_mail(tmp_path, recorder, BOB, "recipient deregistered")
    assert settled == 2
    assert storage.read_msg(tmp_path, BOB, "m1") is None
    assert (tmp_path / "history" / "m1.json").exists()
    assert any("bounce m1" in line for line in recorder.lines) is False
    assert any("bounce m2" in line for line in recorder.lines) is True


def test_cwd_reanchor_skips_queue_anchored_records(tmp_path, monkeypatch):
    recorder = Recorder()
    snap = {"": {"slots": {}, "panes": {"%17": {"pane_pid": "700", "cwd": "/mnt/d/000-project", "slot": "claudes:codex主控"}}}}
    anchored = {
        "agent_id": "win-codex",
        "cli": "codex",
        "cwd": "/mnt/d/000-project",
        "pane_id": "",
        "spawn_cmd": None,
        "ssh_alias": "",
        "codex_bin": "/mnt/c/codex.exe",
        "codex_home": "/mnt/c/.codex",
        "codex_thread": "aaaa5c8b-07a4-7f61-a73c-312c7a2d915e",
    }
    reg = {"agents": {"win-codex": anchored}}
    hubd.reanchor_cwd_panes(reg, tmp_path, recorder, snap)
    assert reg["agents"]["win-codex"]["pane_id"] == ""


def test_scan_relays_fallback_envelope_to_home_hub(tmp_path, monkeypatch):
    from common import sshio

    recorder = Recorder()
    monkeypatch.setattr(hubd.tmuxio, "prime_injection", recorder.fake_inject)
    relayed = []

    def fake_write(alias, envelope):
        relayed.append((alias, envelope["msg_id"]))
        return sshio.REMOTE_OK

    monkeypatch.setattr(hubd.sshio, "write_remote_envelope", fake_write)
    record = codex_record(pane_id="", pane_pid="", ssh_alias="host-b")
    paths.ensure_layout(tmp_path)
    storage.enqueue(tmp_path, envelope_to_bob("m1"))
    hubd.step(tmp_path, {"agents": {BOB: record}}, {}, recorder, time.time(), {BOB: True})
    assert relayed == [("host-b", "m1")]
    assert recorder.injects == []
    assert storage.read_msg(tmp_path, BOB, "m1") is None
    assert (tmp_path / "history" / "m1.json").exists()
    assert any("relayed" in line for line in recorder.lines)
    assert not any("bounce" in line or "FAILED" in line for line in recorder.lines)


def test_scan_archives_injected_mirror_copy_without_relay(tmp_path, monkeypatch):
    recorder = Recorder()
    monkeypatch.setattr(hubd.tmuxio, "prime_injection", recorder.fake_inject)

    def forbid_write(alias, envelope):
        raise AssertionError("已投递镜像副本不得再直投")

    monkeypatch.setattr(hubd.sshio, "write_remote_envelope", forbid_write)
    record = codex_record(pane_id="", pane_pid="", ssh_alias="host-b")
    paths.ensure_layout(tmp_path)
    storage.enqueue(tmp_path, envelope_to_bob("m1"))
    storage.stamp_injected(tmp_path, BOB, "m1", time.time() - hubd.REINJECT_GUARD_SECONDS - 10.0)
    hubd.step(tmp_path, {"agents": {BOB: record}}, {}, recorder, time.time(), {BOB: True})
    assert storage.read_msg(tmp_path, BOB, "m1") is None
    assert (tmp_path / "history" / "m1.json").exists()
    assert not any("bounce" in line or "FAILED" in line for line in recorder.lines)


def test_sweep_relay_unreachable_retries_then_gives_up(tmp_path, monkeypatch):
    from common import sshio

    recorder = Recorder()
    monkeypatch.setattr(hubd.sshio, "write_remote_envelope", lambda alias, envelope: sshio.REMOTE_UNREACHABLE)
    now = time.time()
    stale_envelope = envelope_to_bob("m1")
    stale_envelope["created_at"] = now - hubd.OFFLINE_STALL_SECONDS - 60.0
    paths.ensure_layout(tmp_path)
    storage.enqueue(tmp_path, stale_envelope)
    record = codex_record(pane_id="", pane_pid="", ssh_alias="host-b")
    reg = {"agents": {BOB: record}}

    hubd.sweep_offline_stalled(tmp_path, recorder, reg, {BOB: False}, now, {})
    envelope = storage.read_msg(tmp_path, BOB, "m1")
    assert envelope is not None and envelope["home_relay_first_at"] == now
    assert any("relay-retry" in line for line in recorder.lines)
    assert not any("回弹" in line for line in recorder.lines)

    hubd.sweep_offline_stalled(tmp_path, recorder, reg, {BOB: False}, now + hubd.RELAY_RETRY_SECONDS + 1.0, {})
    assert storage.read_msg(tmp_path, BOB, "m1") is not None
    assert storage.read_msg(tmp_path, BOB, "m1")["home_relay_last_try"] == now + hubd.RELAY_RETRY_SECONDS + 1.0

    hubd.sweep_offline_stalled(
        tmp_path, recorder, reg, {BOB: False}, now + hubd.RELAY_GIVEUP_SECONDS + 1.0, {}
    )
    assert (tmp_path / "queue" / BOB / "m1.failed").exists()
    assert any("relay-giveup" in line and "回弹" in line for line in recorder.lines)
    bounce_dir = tmp_path / "queue" / "claude-h-1"
    assert bounce_dir.is_dir() and len(list(bounce_dir.glob("*.msg"))) == 1


def test_scan_discards_duplicate_of_archived_msg(tmp_path, monkeypatch):
    recorder = Recorder()
    monkeypatch.setattr(hubd.tmuxio, "prime_injection", recorder.fake_inject)
    record = codex_record()
    paths.ensure_layout(tmp_path)
    storage.enqueue(tmp_path, envelope_to_bob("m1"))
    storage.archive_msg(tmp_path, BOB, "m1")
    storage.enqueue(tmp_path, envelope_to_bob("m1"))
    deliveries = {}
    hubd.step(tmp_path, {"agents": {BOB: record}}, deliveries, recorder, time.time(), {BOB: True})
    assert deliveries == {}
    assert recorder.injects == []
    assert not (tmp_path / "queue" / BOB / "m1.msg").exists()
    assert (tmp_path / "history" / "m1.json").exists()
    assert any("duplicate" in line for line in recorder.lines)


def test_slow_cycle_reanchors_win_bridge_record_and_clears_self_alias(tmp_path, monkeypatch):
    recorder = Recorder()
    paths.ensure_layout(tmp_path)
    record = record_for_bob(pane_id="", pane_pid="")
    record.update(
        cli="unknown",
        cwd="/mnt/d/000-自制软件/aicontest",
        ssh_alias="host-b",
        started_at=940.0,
    )
    registry.apply_batch(tmp_path, {BOB: record})
    reg = {"agents": {BOB: record}}
    anchor = {
        "codex_bin": "/mnt/c/Users/winuser/AppData/Local/OpenAI/Codex/bin/h/codex.exe",
        "codex_home": "/mnt/c/Users/winuser/.codex",
        "codex_thread": "01a1af83-1630-7950-998b-b7b077c54f5f",
    }
    monkeypatch.setattr(
        hubd.codexq, "locate_win", lambda cwd: dict(anchor) if cwd == record["cwd"] else {}
    )

    reanchored = hubd.sweep_win_bridge_anchors(reg, tmp_path, recorder, 1000.0)

    assert reanchored == 1
    stored = registry.get(tmp_path, BOB)
    assert stored["codex_thread"] == anchor["codex_thread"]
    assert stored["codex_bin"] == anchor["codex_bin"]
    assert stored["ssh_alias"] == ""
    assert hubd.codexq.anchors_complete(stored)
    assert record["codex_thread"] == anchor["codex_thread"]
    assert any("win-bridge-reanchored" in line for line in recorder.lines)


def test_slow_cycle_win_bridge_reanchor_guard_rails(tmp_path, monkeypatch):
    recorder = Recorder()
    paths.ensure_layout(tmp_path)
    fresh_unanchored = record_for_bob(pane_id="", pane_pid="")
    fresh_unanchored.update(cli="unknown", cwd="/mnt/d/proj", started_at=990.0)
    stale_unanchored = record_for_bob(pane_id="", pane_pid="")
    stale_unanchored.update(cli="unknown", cwd="/mnt/d/proj", started_at=-1000.0)
    anchored = record_for_bob(pane_id="", pane_pid="")
    anchored.update(
        cli="unknown",
        cwd="/mnt/d/proj",
        started_at=990.0,
        codex_bin="/usr/bin/codex",
        codex_home="/home/b/.codex",
        codex_thread="t-1",
    )
    posix_claude = record_for_bob(pane_id="", pane_pid="")
    posix_claude.update(cli="claude", cwd="/mnt/d/proj", started_at=990.0)
    agents = {
        "fresh-unanchored": fresh_unanchored,
        "stale-unanchored": stale_unanchored,
        "anchored": anchored,
        "posix-claude": posix_claude,
    }
    registry.apply_batch(tmp_path, agents)
    calls: list[str] = []
    monkeypatch.setattr(hubd.codexq, "locate_win", lambda cwd: calls.append(cwd) or {})

    reanchored = hubd.sweep_win_bridge_anchors({"agents": agents}, tmp_path, recorder, 1000.0)

    assert calls == ["/mnt/d/proj"]
    assert reanchored == 0
    assert "codex_bin" not in registry.get(tmp_path, "stale-unanchored")
    assert "codex_bin" not in registry.get(tmp_path, "fresh-unanchored")
    assert not any("win-bridge-reanchored" in line for line in recorder.lines)


def test_queue_dispatch_reanchors_stale_bin_and_uses_fresh(tmp_path, monkeypatch):
    recorder = Recorder()
    monkeypatch.setattr(hubd.tmuxio, "prime_injection", recorder.fake_inject)
    monkeypatch.setattr(hubd.tmuxio, "pane_created", lambda pane, ssh=None: 0.0)
    monkeypatch.setattr(hubd.codexq, "daemon_alive", lambda home: True)
    stale = codex_record(
        codex_thread="01a15887-ec89-7df1-99aa-50888f2246a9",
        codex_bin="/mnt/c/Users/winuser/AppData/Local/OpenAI/Codex/bin/oldhash/codex.exe",
        cwd="/mnt/d/000-project",
        pane_id="",
    )
    registry.upsert(tmp_path, BOB, stale)
    fresh = {
        "codex_thread": "01a15887-ec89-7df1-99aa-50888f2246a9",
        "codex_bin": "/mnt/c/Users/winuser/AppData/Local/OpenAI/Codex/bin/newhash/codex.exe",
        "codex_home": "/mnt/c/Users/winuser/.codex",
    }
    monkeypatch.setattr(hubd.codexq, "locate_win", lambda cwd: dict(fresh))
    calls = []

    def fake_enqueue(codex_bin, codex_home, thread_id, message):
        calls.append((codex_bin, str(codex_home), thread_id))
        return None, ""

    monkeypatch.setattr(hubd.codexq, "enqueue_async", fake_enqueue)
    paths.ensure_layout(tmp_path)
    storage.enqueue(tmp_path, envelope_to_bob("m1"))
    run_codex_step(tmp_path, recorder, {}, time.time(), record=stale)

    assert calls == [(fresh["codex_bin"], fresh["codex_home"], fresh["codex_thread"])]
    stored = registry.load(tmp_path)["agents"][BOB]
    assert stored["codex_bin"] == fresh["codex_bin"]
    assert stored["codex_home"] == fresh["codex_home"]
    assert any("queue-thread-reanchored" in line for line in recorder.lines)


def test_reanchor_cwd_panes_revives_dead_anchor(tmp_path):
    recorder = Recorder()
    reg = registry_with_bob(record_for_bob())
    reg["agents"]["claude-h-9-ops"] = {
        "agent_id": "claude-h-9-ops", "cli": "claude", "host": "localhost",
        "pane_id": "%13", "pane_pid": "782071", "slot": "blobtest:bash",
        "cwd": "/home/u/workspace/ops", "spawn_cmd": None,
    }
    registry.apply_batch(tmp_path, {"claude-h-9-ops": reg["agents"]["claude-h-9-ops"]})
    snapshots = {"": {"panes": {
        "%12": {"pane_pid": "429222", "slot": "claudes:ops", "pane_created": "0", "cwd": "/home/u/workspace/ops", "command": "claude"},
    }, "slots": {}}}
    hubd.reanchor_cwd_panes(reg, tmp_path, recorder, snapshots)
    ops = registry.load(tmp_path)["agents"]["claude-h-9-ops"]
    assert ops["pane_id"] == "%12"
    assert ops["pane_pid"] == "429222"
    assert ops["slot"] == "claudes:ops"
    assert any("死锚重锚" in line and "原pane %13" in line for line in recorder.lines)


def test_reanchor_cwd_panes_leaves_live_anchor_alone(tmp_path):
    recorder = Recorder()
    reg = registry_with_bob(record_for_bob())
    reg["agents"]["claude-h-9-ops"] = {
        "agent_id": "claude-h-9-ops", "cli": "claude", "host": "localhost",
        "pane_id": "%13", "pane_pid": "782071", "slot": "blobtest:bash",
        "cwd": "/home/u/workspace/ops", "spawn_cmd": None,
    }
    registry.apply_batch(tmp_path, {"claude-h-9-ops": reg["agents"]["claude-h-9-ops"]})
    snapshots = {"": {"panes": {
        "%13": {"pane_pid": "782071", "slot": "blobtest:bash", "pane_created": "0", "cwd": "/mnt/d/other", "command": "bash"},
        "%12": {"pane_pid": "429222", "slot": "claudes:ops", "pane_created": "0", "cwd": "/home/u/workspace/ops", "command": "claude"},
    }, "slots": {}}}
    hubd.reanchor_cwd_panes(reg, tmp_path, recorder, snapshots)
    ops = registry.load(tmp_path)["agents"]["claude-h-9-ops"]
    assert ops["pane_id"] == "%13"
    assert not any("re-anchored claude-h-9-ops" in line for line in recorder.lines)


def test_orphan_sweep_skips_when_registry_transiently_unreadable(tmp_path, monkeypatch):
    recorder = Recorder()
    ghost_env = envelope_to_bob()
    ghost_env["to"] = "ghost-9"
    storage.enqueue(tmp_path, ghost_env)
    reg = {"agents": {BOB: record_for_bob()}}

    def unavailable(root, on_corrupt=None):
        raise hubd.registry.RegistryUnavailable("EMFILE")

    monkeypatch.setattr(hubd.registry, "try_load", unavailable)
    assert hubd.sweep_orphan_queues(tmp_path, recorder, reg) == []
    assert (storage.queue_dir(tmp_path, "ghost-9") / "m1.msg").exists()
    assert not any(line.startswith("orphan-sweep") for line in recorder.lines)
