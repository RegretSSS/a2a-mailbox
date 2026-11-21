import time
import types

from common import codexq

UUID = "aaaa5c8b-07a4-7f61-a73c-312c7a2d915e"
CODEX_ARGV = ["codex", "resume", UUID]
BASH_ARGV = ["bash"]
CWD = "/home/u/workspace/a2a-mailbox"
DAEMON_PID_JSON = (
    '{"pid":3883200,"processStartTime":"Tue Nov  3 18:47:56 2026",'
    '"processIdentity":{"bootId":"a0b36d03-9da0-470c-bca6-9a6e73c7521c","startTicks":37777663}}'
)


def fake_listing(lines):
    def run(cmd, **kwargs):
        return types.SimpleNamespace(returncode=0, stdout="\n".join(lines))

    return run


def test_locate_tui_returns_sole_codex_pane_matching_cwd(monkeypatch):
    monkeypatch.setattr(
        codexq.subprocess,
        "run",
        fake_listing([f"%11?2485588?{CWD}", f"%51?2269702?{CWD}"]),
    )
    monkeypatch.setattr(codexq, "read_cmdline", lambda pid: CODEX_ARGV if pid == 2269702 else BASH_ARGV)
    assert codexq.locate_tui(CWD) == {"pane_id": "%51", "pane_pid": "2269702", "thread": UUID}


def test_locate_tui_rejects_ambiguous_codex_panes(monkeypatch):
    monkeypatch.setattr(
        codexq.subprocess,
        "run",
        fake_listing([f"%51?2269702?{CWD}", f"%52?2269800?{CWD}"]),
    )
    monkeypatch.setattr(codexq, "read_cmdline", lambda pid: CODEX_ARGV)
    assert codexq.locate_tui(CWD) == {}


def test_locate_tui_skips_foreign_cwd_panes(monkeypatch):
    monkeypatch.setattr(
        codexq.subprocess,
        "run",
        fake_listing([f"%51?2269702?/elsewhere"]),
    )
    monkeypatch.setattr(codexq, "read_cmdline", lambda pid: CODEX_ARGV)
    assert codexq.locate_tui(CWD) == {}


def test_locate_tui_tolerates_missing_tmux(monkeypatch):
    monkeypatch.setattr(
        codexq.subprocess,
        "run",
        lambda cmd, **kwargs: types.SimpleNamespace(returncode=1, stdout=""),
    )
    assert codexq.locate_tui(CWD) == {}

    def raise_oserror(cmd, **kwargs):
        raise OSError("no tmux server")

    monkeypatch.setattr(codexq.subprocess, "run", raise_oserror)
    assert codexq.locate_tui(CWD) == {}


def test_locate_tui_keeps_pane_when_argv_has_no_thread(monkeypatch):
    monkeypatch.setattr(
        codexq.subprocess,
        "run",
        fake_listing([f"%51?2269702?{CWD}"]),
    )
    monkeypatch.setattr(codexq, "read_cmdline", lambda pid: ["codex"])
    assert codexq.locate_tui(CWD) == {"pane_id": "%51", "pane_pid": "2269702", "thread": ""}


def test_parse_daemon_pid_accepts_json_pidfile():
    assert codexq.parse_daemon_pid(DAEMON_PID_JSON) == 3883200


def test_parse_daemon_pid_accepts_plain_pidfile():
    assert codexq.parse_daemon_pid("3883200\n") == 3883200


def test_parse_daemon_pid_rejects_garbage():
    assert codexq.parse_daemon_pid("") == 0
    assert codexq.parse_daemon_pid("not a pid") == 0
    assert codexq.parse_daemon_pid('{"pid":null}') == 0
    assert codexq.parse_daemon_pid('{"pid":"abc"}') == 0


def test_locate_win_matches_session_cwd(tmp_path):
    users = tmp_path / "Users"
    profile = users / "one"
    home = profile / ".codex"
    sessions = home / "sessions" / "2026" / "11" / "03"
    sessions.mkdir(parents=True)
    bin_dir = profile / "AppData" / "Local" / "OpenAI" / "Codex" / "bin" / "abc123"
    bin_dir.mkdir(parents=True)
    (bin_dir / "codex.exe").write_text("")
    rollout = sessions / f"rollout-2026-11-03T20-27-03-{UUID}_01a1a160-923d-7fc2-a62d-29ce433ce1cd.jsonl"
    rollout.write_text('{"type":"session_meta","payload":{"id":"' + UUID + '","cwd":"D:\\\\000-project"}}\n')
    found = codexq.locate_win("/mnt/d/000-project", users_root=users)
    assert found["codex_thread"] == UUID
    assert found["codex_bin"].endswith("codex.exe")
    assert found["codex_home"] == str(home)


def test_locate_win_rejects_non_windows_cwd(tmp_path):
    assert codexq.locate_win("/home/u/workspace", users_root=tmp_path) == {}


def test_locate_win_skips_unreadable_profile(tmp_path):
    users = tmp_path / "Users"
    profile = users / "one"
    home = profile / ".codex"
    sessions = home / "sessions" / "2026" / "11" / "05"
    sessions.mkdir(parents=True)
    bin_dir = profile / "AppData" / "Local" / "OpenAI" / "Codex" / "bin" / "abc123"
    bin_dir.mkdir(parents=True)
    (bin_dir / "codex.exe").write_text("")
    rollout = sessions / f"rollout-2026-11-05T11-00-00-{UUID}_01a1a161-923d-7fc2-a62d-29ce433ce1cd.jsonl"
    rollout.write_text('{"type":"session_meta","payload":{"id":"' + UUID + '","cwd":"D:\\\\000-project"}}\n')
    sandbox = users / "SandboxBlocked"
    sandbox.mkdir()
    (sandbox / ".codex").mkdir()
    (sandbox / ".codex" / "sessions").mkdir()
    (sandbox / ".codex" / "sessions").chmod(0o000)
    try:
        found = codexq.locate_win("/mnt/d/000-project", users_root=users)
    finally:
        (sandbox / ".codex" / "sessions").chmod(0o755)
    assert found["codex_thread"] == UUID


def test_locate_win_prefers_fresh_session_across_profiles(tmp_path):
    import os

    users = tmp_path / "Users"
    sessions_text = '{"payload":{"cwd":"D:\\\\000-project"}}\n'
    stale_profile = users / "aaa"
    stale_sessions = stale_profile / ".codex" / "sessions" / "2026"
    stale_sessions.mkdir(parents=True)
    stale_bin = stale_profile / "AppData" / "Local" / "OpenAI" / "Codex" / "bin" / "old"
    stale_bin.mkdir(parents=True)
    (stale_bin / "codex.exe").write_text("")
    stale_rollout = stale_sessions / f"rollout-2026-11-03T20-27-03-{UUID}.jsonl"
    stale_rollout.write_text(sessions_text)
    fresh_profile = users / "zzz"
    fresh_sessions = fresh_profile / ".codex" / "sessions" / "2026"
    fresh_sessions.mkdir(parents=True)
    fresh_bin = fresh_profile / "AppData" / "Local" / "OpenAI" / "Codex" / "bin" / "new"
    fresh_bin.mkdir(parents=True)
    (fresh_bin / "codex.exe").write_text("")
    fresh_rollout = fresh_sessions / f"rollout-2026-11-04T10-00-00-{UUID}.jsonl"
    fresh_rollout.write_text(sessions_text)
    old_time = time.time() - 86400.0
    os.utime(stale_rollout, (old_time, old_time))

    found = codexq.locate_win("/mnt/d/000-project", users_root=users)
    assert found["codex_home"] == str(fresh_profile / ".codex")
    assert found["codex_bin"] == str(fresh_bin / "codex.exe")
    assert found["codex_thread"] == UUID


def test_locate_win_returns_empty_when_cwd_mismatch(tmp_path):
    users = tmp_path / "Users"
    profile = users / "one"
    sessions = profile / ".codex" / "sessions" / "2026"
    sessions.mkdir(parents=True)
    (profile / "AppData" / "Local" / "OpenAI" / "Codex" / "bin" / "abc" ).mkdir(parents=True)
    (profile / "AppData" / "Local" / "OpenAI" / "Codex" / "bin" / "abc" / "codex.exe").write_text("")
    rollout = sessions / f"rollout-2026-11-03T20-27-03-{UUID}.jsonl"
    rollout.write_text('{"payload":{"cwd":"E:\\\\other"}}\n')
    assert codexq.locate_win("/mnt/d/000-project", users_root=users) == {}
