import importlib.util
import json
import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import lockfile, paths, registry

_SPEC = importlib.util.spec_from_file_location(
    "http_gateway", Path(__file__).resolve().parent.parent / "mcp" / "http_gateway.py"
)
http_gateway = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(http_gateway)


def _refuse_lock(handle):
    raise OSError("hub spawn disabled in tests")


@pytest.fixture(autouse=True)
def no_hub_spawn(monkeypatch):
    monkeypatch.setattr(lockfile, "lock_exclusive", _refuse_lock)
    http_gateway.MODULES.clear()


INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "t", "version": "0"},
    },
}
INITIALIZED = {"jsonrpc": "2.0", "method": "notifications/initialized"}
MCP_ACCEPT = {"accept": "application/json, text/event-stream"}


def sse_json(resp):
    for line in resp.text.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:])
    raise AssertionError(resp.text[:200])


def session(client, agent_id, headers=None):
    resp = client.post(f"/{agent_id}/mcp", json=INIT, headers={**MCP_ACCEPT, **(headers or {})})
    assert resp.status_code == 200
    session_id = resp.headers.get("mcp-session-id")
    assert session_id
    client.post(
        f"/{agent_id}/mcp",
        json=INITIALIZED,
        headers={**MCP_ACCEPT, "mcp-session-id": session_id, **(headers or {})},
    )
    return session_id


def call(client, agent_id, session_id, tool, arguments, headers=None):
    resp = client.post(
        f"/{agent_id}/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        },
        headers={**MCP_ACCEPT, "mcp-session-id": session_id, **(headers or {})},
    )
    assert resp.status_code == 200
    payload = sse_json(resp)
    return json.loads(payload["result"]["content"][0]["text"])


def registered_root(tmp_path, *agent_ids):
    root = tmp_path / "mailbox"
    paths.ensure_layout(root)
    for agent_id in agent_ids:
        registry.upsert(root, agent_id, {"cli": "claude", "pane_id": "%1", "pane_pid": "100"})
    return root


def test_build_app_mounts_registered_agents_with_isolated_identity(tmp_path, monkeypatch):
    root = registered_root(tmp_path, "claude-a", "claude-b")
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(root))
    app = http_gateway.build_app(root)
    with TestClient(app) as client:
        assert sorted(app.state.agents) == ["claude-a", "claude-b"]
        session_a = session(client, "claude-a")
        session_b = session(client, "claude-b")
        result = call(client, "claude-a", session_a, "mail_send", {"to": "claude-b", "body": "probe"})
        assert result["ok"] is True
        inbox = call(client, "claude-b", session_b, "mail_poll", {})
        messages = inbox.get("messages") or []
        assert messages, f"claude-b inbox empty: {inbox}"
        assert messages[0]["from"] == "claude-a"


def test_unregistered_agent_returns_404(tmp_path, monkeypatch):
    root = registered_root(tmp_path, "claude-a")
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(root))
    app = http_gateway.build_app(root)
    with TestClient(app) as client:
        resp = client.post("/claude-ghost/mcp", json=INIT, headers=MCP_ACCEPT)
        assert resp.status_code == 404


def test_healthz_lists_mounted_agents_without_token_on_loopback(tmp_path, monkeypatch):
    root = registered_root(tmp_path, "claude-a")
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(root))
    (root / "http-token").write_text("sekrit")
    monkeypatch.setenv(http_gateway.BIND_ENV, "127.0.0.1")
    app = http_gateway.build_app(root)
    with TestClient(app) as client:
        resp = client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json()["agents"] == ["claude-a"]


def test_token_enforced_on_non_loopback_bind(tmp_path, monkeypatch):
    root = registered_root(tmp_path, "claude-a")
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(root))
    (root / "http-token").write_text("sekrit")
    monkeypatch.setenv(http_gateway.BIND_ENV, "0.0.0.0")
    app = http_gateway.build_app(root)
    with TestClient(app) as client:
        assert client.post("/claude-a/mcp", json=INIT, headers=MCP_ACCEPT).status_code == 401
        headers = {"authorization": "Bearer sekrit"}
        assert client.post("/claude-a/mcp", json=INIT, headers={**MCP_ACCEPT, **headers}).status_code == 200
        kick = client.post("/kick", headers=headers)
        assert kick.status_code == 200
        assert (root / "fed-pull-now").exists()


def test_non_loopback_without_token_serves_503(tmp_path, monkeypatch):
    root = registered_root(tmp_path, "claude-a")
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(root))
    monkeypatch.setenv(http_gateway.BIND_ENV, "0.0.0.0")
    app = http_gateway.build_app(root)
    with TestClient(app) as client:
        resp = client.post("/claude-a/mcp", json=INIT, headers=MCP_ACCEPT)
        assert resp.status_code == 503


def test_kick_flag_filename_contract():
    from hub import hub as hub_mod

    assert http_gateway.KICK_FILENAME == hub_mod.FED_PULL_NOW_FILENAME


def test_forgotten_agent_route_returns_404(tmp_path, monkeypatch):
    root = registered_root(tmp_path, "claude-a", "claude-b")
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(root))
    app = http_gateway.build_app(root)
    with TestClient(app) as client:
        session_id = session(client, "claude-a")
        assert client.post("/claude-a/mcp", json=INIT, headers={**MCP_ACCEPT, "mcp-session-id": session_id}).status_code == 200
        registry.forget(root, "claude-a")
        assert client.post("/claude-a/mcp", json=INIT, headers={**MCP_ACCEPT, "mcp-session-id": session_id}).status_code == 404
        session_b = session(client, "claude-b")
        assert session_b


def test_healthz_requires_token_on_non_loopback(tmp_path, monkeypatch):
    root = registered_root(tmp_path, "claude-a")
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(root))
    (root / "http-token").write_text("sekrit")
    app = http_gateway.build_app(root, bind_host="0.0.0.0")
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 401
        resp = client.get("/healthz", headers={"authorization": "Bearer sekrit"})
        assert resp.status_code == 200
        assert resp.json()["agents"] == ["claude-a"]


def test_corrupt_token_file_does_not_crash_guard(tmp_path, monkeypatch):
    root = registered_root(tmp_path, "claude-a")
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(root))
    (root / "http-token").write_bytes(b"\xff\xfe")
    app = http_gateway.build_app(root, bind_host="0.0.0.0")
    with TestClient(app) as client:
        resp = client.post("/claude-a/mcp", json=INIT, headers=MCP_ACCEPT)
        assert resp.status_code == 503


def test_modules_cached_per_root(tmp_path, monkeypatch):
    root_a = registered_root(tmp_path / "a", "claude-a")
    root_b = registered_root(tmp_path / "b", "claude-a")
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(root_a))
    http_gateway.build_app(root_a)
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(root_b))
    http_gateway.build_app(root_b)
    assert http_gateway.MODULES[(str(root_a), "claude-a")].SELF["agent_id"] == "claude-a"
    assert http_gateway.MODULES[(str(root_b), "claude-a")].SELF["agent_id"] == "claude-a"
    assert len([key for key in http_gateway.MODULES if key[1] == "claude-a"]) == 2


def test_empty_registry_build_warns_on_stderr(tmp_path, monkeypatch, capsys):
    root = tmp_path / "mailbox"
    paths.ensure_layout(root)
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(root))
    app = http_gateway.build_app(root)
    assert app.state.agents == []
    assert "registry" in capsys.readouterr().err
