import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import sshio


class Finished:
    def __init__(self, returncode, stdout):
        self.returncode = returncode
        self.stdout = stdout


def test_remote_ack_exists_positive(monkeypatch):
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        return Finished(0, '{"ack_id": "ack-m1"}')

    monkeypatch.setattr(sshio.subprocess, "run", fake_run)
    assert sshio.remote_ack_exists("host-b", "ack-m1") is True
    assert seen["command"] == ["ssh", "-o", "ControlMaster=auto", "-o", "ControlPath=/tmp/a2a-ssh-%C", "-o", "ControlPersist=60", "-o", "BatchMode=yes", "-o", "ConnectTimeout=3", "host-b", "cat", ".agents-mailbox/acks/ack-m1"]


def test_remote_ack_exists_negative(monkeypatch):
    monkeypatch.setattr(
        sshio.subprocess, "run", lambda command, **kwargs: Finished(1, "")
    )
    assert sshio.remote_ack_exists("host-b", "ack-missing") is False


def test_remote_ack_rejects_unsafe_id(monkeypatch):
    def fail(command, **kwargs):
        raise AssertionError("must not run ssh")

    monkeypatch.setattr(sshio.subprocess, "run", fail)
    assert sshio.remote_ack_exists("host-b", "x; rm -rf /") is False
    assert sshio.remote_ack_exists("host-b", "../registry") is False


def test_read_remote_json_parses(monkeypatch):
    monkeypatch.setattr(
        sshio.subprocess, "run", lambda command, **kwargs: Finished(0, '{"agents": {}}')
    )
    assert sshio.read_remote_json("host-b", ".agents-mailbox/registry.json") == {"agents": {}}


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
