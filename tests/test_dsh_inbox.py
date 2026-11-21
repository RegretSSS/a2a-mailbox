import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import dsh_inbox

RECORD = {
    "agent_id": "dsh-host-a-wsl",
    "cli": "dsh",
    "cwd": "/home/user-a/workspace/deepseek-harness",
    "rpc_inbox_url": "http://127.0.0.1:3080",
}

SESSION_IDLE = {
    "sessionId": "session-idle-1",
    "updatedAt": 1794119491231,
    "running": False,
    "blank": False,
    "cwd": "/home/user-a/workspace/deepseek-harness",
}

SESSION_RUNNING = {
    "sessionId": "session-run-1",
    "updatedAt": 1794120408205,
    "running": True,
    "blank": False,
    "cwd": "/home/user-a/workspace/deepseek-harness",
}

SESSION_BLANK = {
    "sessionId": "session-blank-1",
    "updatedAt": 1794120409000,
    "running": False,
    "blank": True,
    "cwd": "/home/user-a/workspace/deepseek-harness",
}

SESSION_OTHER_CWD = {
    "sessionId": "session-other-1",
    "updatedAt": 1794120409999,
    "running": True,
    "blank": False,
    "cwd": "/tmp",
}


def test_pick_session_prefers_latest_cwd_match_and_skips_blank():
    picked = dsh_inbox.pick_session(
        [SESSION_BLANK, SESSION_IDLE, SESSION_RUNNING, SESSION_OTHER_CWD],
        RECORD["cwd"],
    )
    assert picked is SESSION_RUNNING


def test_pick_session_without_cwd_constraint_still_skips_blank():
    picked = dsh_inbox.pick_session([SESSION_BLANK, SESSION_IDLE], "")
    assert picked is SESSION_IDLE


def test_pick_session_no_match_returns_none():
    assert dsh_inbox.pick_session([SESSION_OTHER_CWD], RECORD["cwd"]) is None


def test_enqueue_without_url_reports_missing_endpoint(tmp_path):
    record = dict(RECORD, rpc_inbox_url="")
    outcome = dsh_inbox.enqueue(record, "abc123", "wake", time.time(), tmp_path)
    assert outcome.ok is False
    assert "rpc_inbox_url" in outcome.reason


def test_enqueue_queues_idle_session_and_steers_running_session(tmp_path, monkeypatch):
    calls = []

    def fake_call_rpc(url, cookie, endpoint, args, rpc_id):
        calls.append((endpoint, args))
        if endpoint == "session/list":
            return {"items": [SESSION_IDLE]}
        return {"accepted": True}

    monkeypatch.setattr(dsh_inbox, "call_rpc", fake_call_rpc)
    monkeypatch.setattr(dsh_inbox, "ensure_cookie", lambda url, agent_id, now, root=None: "dsh-auth=x")
    outcome = dsh_inbox.enqueue(RECORD, "abc123", "wake-text", 1000.0, tmp_path)
    assert outcome.ok is True
    assert outcome.mode == "queue"
    assert outcome.session_id == "session-idle-1"
    prompt = calls[1][1]["request"]
    assert prompt["requestId"] == "a2a-abc123"
    assert prompt["mode"] == "queue"
    assert prompt["content"] == [{"type": "text", "text": "wake-text"}]

    calls.clear()

    def fake_call_rpc_running(url, cookie, endpoint, args, rpc_id):
        if endpoint == "session/list":
            return {"items": [SESSION_RUNNING]}
        return {"accepted": True}

    monkeypatch.setattr(dsh_inbox, "call_rpc", fake_call_rpc_running)
    outcome2 = dsh_inbox.enqueue(RECORD, "def456", "wake-text", 1000.0, tmp_path)
    assert outcome2.ok is True
    assert outcome2.mode == "steer"
    assert outcome2.session_id == "session-run-1"


def test_enqueue_failure_surfaces_reason_without_raising(tmp_path, monkeypatch):
    def fake_call_rpc(url, cookie, endpoint, args, rpc_id):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(dsh_inbox, "call_rpc", fake_call_rpc)
    monkeypatch.setattr(dsh_inbox, "ensure_cookie", lambda url, agent_id, now, root=None: "dsh-auth=x")
    outcome = dsh_inbox.enqueue(RECORD, "abc123", "wake", time.time(), tmp_path)
    assert outcome.ok is False
    assert "connection refused" in outcome.reason


def test_ensure_cookie_uses_cached_value_within_refresh_window(tmp_path, monkeypatch):
    store = tmp_path / "dsh-hosts" / f"{RECORD['agent_id']}.cookie"
    store.parent.mkdir(parents=True)
    store.write_text("dsh-auth=fresh")
    store.touch()
    now = time.time() + dsh_inbox.COOKIE_MAX_AGE_SECONDS - dsh_inbox.COOKIE_REFRESH_MARGIN_SECONDS - 3600
    monkeypatch.setattr(dsh_inbox, "exchange_cookie", lambda url, token: "dsh-auth=should-not-happen")
    assert dsh_inbox.ensure_cookie("http://x", RECORD["agent_id"], now, tmp_path) == "dsh-auth=fresh"


def test_ensure_cookie_refreshes_from_token_when_stale(tmp_path, monkeypatch):
    hosts = tmp_path / "dsh-hosts"
    hosts.mkdir(parents=True)
    cookie_store = hosts / f"{RECORD['agent_id']}.cookie"
    cookie_store.write_text("dsh-auth=old")
    old_enough = time.time() - 10
    cookie_store.touch()
    import os

    os.utime(cookie_store, (old_enough - dsh_inbox.COOKIE_MAX_AGE_SECONDS, old_enough - dsh_inbox.COOKIE_MAX_AGE_SECONDS))
    (hosts / f"{RECORD['agent_id']}.token").write_text("launch-token")
    monkeypatch.setattr(
        dsh_inbox, "exchange_cookie", lambda url, token: "dsh-auth=new" if token == "launch-token" else "?"
    )
    got = dsh_inbox.ensure_cookie("http://x", RECORD["agent_id"], old_enough, tmp_path)
    assert got == "dsh-auth=new"
    assert cookie_store.read_text() == "dsh-auth=new"


def test_ensure_cookie_without_token_names_the_missing_file(tmp_path):
    try:
        dsh_inbox.ensure_cookie("http://x", RECORD["agent_id"], time.time(), tmp_path)
    except RuntimeError as exc:
        assert str(tmp_path) in str(exc)
        assert "token" in str(exc)
    else:
        raise AssertionError("缺 token 应抛 RuntimeError")


def test_cwd_matches_normalizes_win_drive_paths():
    assert dsh_inbox.cwd_matches("D:\\win-lab\\dsh-test", "/mnt/d/win-lab/dsh-test")
    assert not dsh_inbox.cwd_matches("D:\\elsewhere", "/mnt/d/win-lab/dsh-test")


def test_cwd_matches_normalizes_wsl_unc_share():
    assert dsh_inbox.cwd_matches("\\\\wsl.localhost\\Ubuntu\\home\\u\\x", "/home/u/x")
    assert dsh_inbox.cwd_matches("\\\\wsl$\\Ubuntu\\home\\u\\x", "/home/u/x")
    assert not dsh_inbox.cwd_matches("\\\\wsl.localhost\\Ubuntu\\home\\u\\x", "/home/u/y")


def test_cwd_matches_pure_posix_keeps_case_sensitivity():
    assert not dsh_inbox.cwd_matches("/home/Bundle", "/home/bundle")
    assert dsh_inbox.cwd_matches("/home/bundle", "/home/bundle")


def test_cwd_matches_win_shaped_side_case_insensitive():
    assert dsh_inbox.cwd_matches("D:\\100-ZiZhi\\A", "/mnt/d/100-zizhi/a")


def test_pick_session_reaches_win_cwd_session():
    items = [
        {"sessionId": "blank-1", "blank": True, "cwd": "D:\\win-lab\\dsh-test", "updatedAt": 50},
        {"sessionId": "hit-1", "blank": False, "cwd": "D:\\win-lab\\dsh-test", "updatedAt": 9},
        {"sessionId": "elsewhere", "blank": False, "cwd": "D:\\elsewhere", "updatedAt": 99},
    ]
    picked = dsh_inbox.pick_session(items, "/mnt/d/win-lab/dsh-test")
    assert picked is not None and picked["sessionId"] == "hit-1"
    assert dsh_inbox.pick_session(items, "/mnt/d/no-such-dir") is None
