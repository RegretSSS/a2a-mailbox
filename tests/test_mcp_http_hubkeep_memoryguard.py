import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from common import hubkeep, memoryguard, registry


def test_memoryguard_maybe_trim_throttles(monkeypatch):
    calls = {"n": 0}

    def spy():
        calls["n"] += 1
        return True

    monkeypatch.setattr(memoryguard, "trim_now", spy)
    memoryguard._last_trim_at = 1000.0
    memoryguard.maybe_trim(now=1010.0)
    assert calls["n"] == 0
    memoryguard.maybe_trim(now=1000.0 + memoryguard.TRIM_INTERVAL_SECONDS + 1)
    assert calls["n"] == 1


def test_memoryguard_trim_now_resets_clock():
    memoryguard._last_trim_at = 0.0
    memoryguard.trim_now()
    assert memoryguard._last_trim_at > 0


def test_hubkeep_spawn_is_detached(monkeypatch):
    spawned: dict = {}

    def fake_popen(args, **kwargs):
        spawned["args"] = args
        spawned["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(hubkeep, "_systemctl", lambda args: None)
    monkeypatch.setattr(hubkeep.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(hubkeep.time, "sleep", lambda seconds: None)
    liveness = iter([[], [9999]])
    monkeypatch.setattr(hubkeep, "hub_pids", lambda: next(liveness))
    assert hubkeep.ensure_hub_running() is True
    assert spawned["kwargs"]["start_new_session"] is True
    assert spawned["kwargs"]["close_fds"] is True
    assert spawned["kwargs"]["stdin"] is hubkeep.subprocess.DEVNULL
    assert spawned["kwargs"]["stdout"] is hubkeep.subprocess.DEVNULL
    assert spawned["kwargs"]["stderr"] is hubkeep.subprocess.DEVNULL


def test_hubkeep_prefers_systemd_unit(monkeypatch):
    systemctl_calls: list = []
    monkeypatch.setattr(hubkeep, "_systemctl", lambda args: systemctl_calls.append(args) or 0)
    monkeypatch.setattr(hubkeep.time, "sleep", lambda seconds: None)
    liveness = iter([[], [9999]])
    monkeypatch.setattr(hubkeep, "hub_pids", lambda: next(liveness))
    assert hubkeep.ensure_hub_running() is True
    assert systemctl_calls[0][:2] == ["cat", "a2a-hub"]
    assert systemctl_calls[1][:2] == ["start", "a2a-hub"]


def test_hubkeep_skips_when_alive(monkeypatch):
    systemctl_calls: list = []
    monkeypatch.setattr(hubkeep, "_systemctl", lambda args: systemctl_calls.append(args) or 0)
    monkeypatch.setattr(hubkeep, "hub_pids", lambda: [4242])
    assert hubkeep.ensure_hub_running() is True
    assert systemctl_calls == []


class FakeHeaders:
    def __init__(self, agent_id: str):
        self.agent_id = agent_id

    def get(self, name: str, default: str = "") -> str:
        return self.agent_id if name == "x-a2a-agent" else default


class FakeRequest:
    def __init__(self, agent_id: str):
        self.headers = FakeHeaders(agent_id)


class FakeRequestContext:
    def __init__(self, agent_id: str):
        self.request = FakeRequest(agent_id)


class FakeCtx:
    def __init__(self, agent_id: str):
        self.request_context = FakeRequestContext(agent_id)


@pytest.fixture
def mailbox_mod(tmp_path, monkeypatch):
    import importlib.util

    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    spec = importlib.util.spec_from_file_location(
        "mailbox_binding_mod", str(Path(__file__).resolve().parent.parent / "mcp" / "mailbox_mcp.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.SELF = {}
    return module


def test_caller_binding_http_header_registered(mailbox_mod, tmp_path):
    registry.upsert(tmp_path, "pi-h-1", {"cli": "pi", "pane_id": "%1"})
    agent_id, error = mailbox_mod.caller_binding(FakeCtx("pi-h-1"))
    assert (agent_id, error) == ("pi-h-1", "")


def test_caller_binding_http_header_unknown_rejected(mailbox_mod):
    agent_id, error = mailbox_mod.caller_binding(FakeCtx("not-registered"))
    assert agent_id == ""
    assert "X-A2A-Agent" in error


def test_caller_binding_http_no_header_no_self_rejected(mailbox_mod):
    agent_id, error = mailbox_mod.caller_binding(FakeCtx(""))
    assert agent_id == ""
    assert "X-A2A-Agent" in error


def test_caller_binding_gateway_prefilled_self_falls_back(mailbox_mod, tmp_path):
    registry.upsert(tmp_path, "claude-gw-1", {"cli": "claude", "pane_id": "%2"})
    mailbox_mod.SELF = {"agent_id": "claude-gw-1"}
    agent_id, error = mailbox_mod.caller_binding(FakeCtx(""))
    assert (agent_id, error) == ("claude-gw-1", "")


def test_caller_binding_gateway_header_mismatch_rejected(mailbox_mod, tmp_path):
    registry.upsert(tmp_path, "claude-gw-1", {"cli": "claude", "pane_id": "%2"})
    registry.upsert(tmp_path, "pi-victim-1", {"cli": "pi", "pane_id": "%3"})
    mailbox_mod.SELF = {"agent_id": "claude-gw-1"}
    agent_id, error = mailbox_mod.caller_binding(FakeCtx("pi-victim-1"))
    assert agent_id == ""
    assert "不一致" in error


def test_caller_binding_gateway_header_match_allowed(mailbox_mod, tmp_path):
    registry.upsert(tmp_path, "claude-gw-1", {"cli": "claude", "pane_id": "%2"})
    mailbox_mod.SELF = {"agent_id": "claude-gw-1"}
    agent_id, error = mailbox_mod.caller_binding(FakeCtx("claude-gw-1"))
    assert (agent_id, error) == ("claude-gw-1", "")


def test_mounted_reanchor_preserves_registry_identity(tmp_path, monkeypatch):
    import importlib

    spec = importlib.util.spec_from_file_location(
        "mounted_probe", "mcp/mailbox_mcp.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    registry.upsert(tmp_path, "pi-h-anchor", {"cli": "pi", "cwd": "/proj/a", "pane_id": "%3", "pane_pid": "31"})
    monkeypatch.setattr(module, "MOUNTED_AGENT_ID", "pi-h-anchor")
    monkeypatch.setattr(module, "MOUNTED_CWD", "/proj/a")
    monkeypatch.setattr(module, "MOUNTED_CLI", "pi")
    monkeypatch.setattr(module.detect, "detect_cli", lambda: "unknown")

    record = module.register_record("pi-h-anchor")
    assert record["cli"] == "pi"
    assert record["cwd"] == "/proj/a"
    assert record["pane_id"] == ""
    on_disk = registry.get(tmp_path, "pi-h-anchor")
    assert on_disk["cli"] == "pi"
    assert on_disk["pane_id"] == ""
