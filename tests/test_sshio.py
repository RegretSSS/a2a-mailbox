import sys
from pathlib import Path
from subprocess import TimeoutExpired

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import sshio


class Finished:
    def __init__(self, returncode, stdout):
        self.returncode = returncode
        self.stdout = stdout


def test_remote_ack_state_present(monkeypatch):
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        return Finished(0, '{"ack_id": "ack-m1"}')

    monkeypatch.setattr(sshio.subprocess, "run", fake_run)
    assert sshio.remote_ack_state("host-b", "ack-m1") == sshio.REMOTE_ACK_PRESENT
    assert seen["command"] == ["ssh", "-o", "ControlMaster=auto", "-o", "ControlPath=/tmp/a2a-ssh-%C", "-o", "ControlPersist=3600", "-o", "BatchMode=yes", "-o", "ConnectTimeout=3", "host-b", "cat", ".agents-mailbox/acks/ack-m1"]


def test_remote_ack_state_absent_on_missing_file(monkeypatch):
    monkeypatch.setattr(
        sshio.subprocess, "run", lambda command, **kwargs: Finished(1, "")
    )
    assert sshio.remote_ack_state("host-b", "ack-missing") == sshio.REMOTE_ACK_ABSENT


def test_remote_ack_state_empty_file_is_absent(monkeypatch):
    monkeypatch.setattr(
        sshio.subprocess, "run", lambda command, **kwargs: Finished(0, "")
    )
    assert sshio.remote_ack_state("host-b", "ack-blank") == sshio.REMOTE_ACK_ABSENT


def test_remote_ack_state_unreachable_on_ssh_error(monkeypatch):
    monkeypatch.setattr(
        sshio.subprocess, "run", lambda command, **kwargs: Finished(255, "")
    )
    assert sshio.remote_ack_state("host-b", "ack-m1") == sshio.REMOTE_ACK_UNREACHABLE

    def explode(command, **kwargs):
        raise TimeoutExpired(cmd="ssh", timeout=12)

    monkeypatch.setattr(sshio.subprocess, "run", explode)
    assert sshio.remote_ack_state("host-b", "ack-m1") == sshio.REMOTE_ACK_UNREACHABLE


def test_remote_ack_rejects_unsafe_id(monkeypatch):
    def fail(command, **kwargs):
        raise AssertionError("must not run ssh")

    monkeypatch.setattr(sshio.subprocess, "run", fail)
    assert sshio.remote_ack_state("host-b", "x; rm -rf /") == sshio.REMOTE_ACK_ABSENT
    assert sshio.remote_ack_state("host-b", "../registry") == sshio.REMOTE_ACK_ABSENT




def test_write_remote_envelope_builds_atomic_script(monkeypatch):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["input"] = kwargs.get("input")
        return Finished(0, "")

    monkeypatch.setattr(sshio.subprocess, "run", fake_run)
    envelope = {"msg_id": "w1", "to": "codex-host-b-000-host-c", "body": "直投"}
    status = sshio.write_remote_envelope("host-b", envelope)
    assert status == sshio.REMOTE_OK
    assert captured["command"][-2:] == ["python3", "-"]
    assert "'codex-host-b-000-host-c'" in captured["input"]
    assert "'w1'" in captured["input"]
    assert "os.replace(tmp, target)" in captured["input"]
    assert "直投" in captured["input"]


def test_write_remote_envelope_status_mapping(monkeypatch):
    monkeypatch.setattr(sshio.subprocess, "run", lambda command, **kwargs: Finished(255, ""))
    assert sshio.write_remote_envelope("host-b", {"msg_id": "w1", "to": "a-b"}) == sshio.REMOTE_UNREACHABLE
    monkeypatch.setattr(sshio.subprocess, "run", lambda command, **kwargs: Finished(1, ""))
    assert sshio.write_remote_envelope("host-b", {"msg_id": "w1", "to": "a-b"}) == sshio.REMOTE_NOT_FOUND


def test_write_remote_envelope_rejects_unsafe_ids(monkeypatch):
    def fail(command, **kwargs):
        raise AssertionError("must not run ssh")

    monkeypatch.setattr(sshio.subprocess, "run", fail)
    assert sshio.write_remote_envelope("host-b", {"msg_id": "../x", "to": "a-b"}) == sshio.REMOTE_BAD_JSON
    assert sshio.write_remote_envelope("host-b", {"msg_id": "w1", "to": "a b"}) == sshio.REMOTE_BAD_JSON
