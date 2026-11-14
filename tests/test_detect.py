import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import detect


def fake_chain(comm_by_pid, parent_by_pid):
    return (
        lambda pid: comm_by_pid.get(pid, ""),
        lambda pid: "",
        lambda pid: parent_by_pid.get(pid, 0),
    )


def test_detect_cli_finds_ancestor():
    comm_reader, cmdline_reader, ppid_reader = fake_chain(
        {10: "python3", 20: "claude", 30: "bash"},
        {10: 20, 20: 30, 30: 1},
    )
    assert detect.detect_cli(pid=10, comm_reader=comm_reader, cmdline_reader=cmdline_reader, ppid_reader=ppid_reader) == "claude"


def test_detect_cli_falls_back_to_cmdline_basename():
    comm_reader, _, ppid_reader = fake_chain(
        {10: "python3", 20: "node"},
        {10: 20, 20: 1},
    )
    cmdline_reader = lambda pid: "/usr/local/bin/codex" if pid == 20 else ""
    assert detect.detect_cli(pid=10, comm_reader=comm_reader, cmdline_reader=cmdline_reader, ppid_reader=ppid_reader) == "codex"


def test_detect_cli_unknown_when_no_match():
    comm_reader, cmdline_reader, ppid_reader = fake_chain(
        {10: "python3", 20: "bash"},
        {10: 20, 20: 1},
    )
    assert detect.detect_cli(pid=10, comm_reader=comm_reader, cmdline_reader=cmdline_reader, ppid_reader=ppid_reader) == "unknown"


def test_build_agent_id_uses_workspace_slug(monkeypatch):
    monkeypatch.setenv("A2A_SSH_ALIAS", "host-b")
    assert detect.build_agent_id("claude", "/home/user-b/workspace/a2a-mailbox") == "claude-host-b-a2a-mailbox"


def test_build_agent_id_explicit_env_wins(monkeypatch):
    monkeypatch.setenv("A2A_SSH_ALIAS", "host-b")
    monkeypatch.setenv("A2A_AGENT_ID", " codex-main-host-b-host-c ")
    assert detect.build_agent_id("unknown", "/mnt/d/000-project") == "codex-main-host-b-host-c"


def test_host_qualifier_prefers_tag_env_then_alias_then_cache(monkeypatch):
    monkeypatch.delenv("A2A_SSH_ALIAS", raising=False)
    monkeypatch.setattr(detect, "read_host_tag_cache", lambda: "host-a")
    monkeypatch.setenv("A2A_HOST_TAG", "Host-a Box")
    assert detect.host_qualifier() == "host-a-box"
    monkeypatch.delenv("A2A_HOST_TAG")
    monkeypatch.setenv("A2A_SSH_ALIAS", "host-b")
    assert detect.host_qualifier() == "host-b"
    monkeypatch.delenv("A2A_SSH_ALIAS")
    assert detect.host_qualifier() == "host-a"


def test_host_qualifier_tailscale_then_hostname_and_caches(monkeypatch, tmp_path):
    monkeypatch.delenv("A2A_SSH_ALIAS", raising=False)
    monkeypatch.delenv("A2A_HOST_TAG", raising=False)
    monkeypatch.setattr(detect, "read_host_tag_cache", lambda: "")
    written = {}
    monkeypatch.setattr(detect, "write_host_tag_cache", lambda tag: written.update(tag=tag))
    monkeypatch.setattr(detect, "local_host", lambda: "localhost")
    monkeypatch.setattr(detect, "tailscale_self_name", lambda: "node-9")
    assert detect.host_qualifier() == "node-9"
    assert written == {"tag": "node-9"}
    monkeypatch.setattr(detect, "tailscale_self_name", lambda: "")
    assert detect.host_qualifier() == "localhost"


def test_host_qualifier_alias_env_wins(monkeypatch):
    monkeypatch.delenv("A2A_HOST_TAG", raising=False)
    monkeypatch.setattr(detect, "read_host_tag_cache", lambda: "")
    monkeypatch.setattr(detect, "tailscale_self_name", lambda: "host-a")
    monkeypatch.setenv("A2A_SSH_ALIAS", "Host-b Box")
    assert detect.host_qualifier() == "host-b-box"


class FinishedStatus:
    def __init__(self, stdout):
        self.stdout = stdout


def test_tailscale_self_name_prefers_dns_label(monkeypatch):
    detect.TS_SELF_CACHE = None
    payload = '{"Self": {"HostName": "office-host-a", "DNSName": "host-a.tail7c4n9v2.ts.net."}}'
    monkeypatch.setattr(
        detect.subprocess, "run", lambda cmd, **kw: FinishedStatus(payload)
    )
    assert detect.tailscale_self_name() == "host-a"


def test_tailscale_self_name_unavailable_returns_empty(monkeypatch):
    detect.TS_SELF_CACHE = None

    def boom(cmd, **kw):
        raise OSError("no interop")

    monkeypatch.setattr(detect.subprocess, "run", boom)
    assert detect.tailscale_self_name() == ""


def test_workspace_slug_sanitizes():
    assert detect.workspace_slug("/mnt/c/Users/user-a/Win Codex_Ws") == "win-codex-ws"
    assert detect.workspace_slug("/") == "root"


def test_agent_id_survives_pane_rebuild(monkeypatch):
    monkeypatch.delenv("A2A_SSH_ALIAS", raising=False)
    monkeypatch.delenv("A2A_HOST_TAG", raising=False)
    monkeypatch.setattr(detect, "read_host_tag_cache", lambda: "")
    monkeypatch.setattr(detect, "tailscale_self_name", lambda: "host-a")
    first = detect.build_agent_id("codex", "/mnt/c/Users/user-a/win-codex-ws")
    second = detect.build_agent_id("codex", "/mnt/c/Users/user-a/win-codex-ws")
    assert first == second == "codex-host-a-win-codex-ws"


def test_claimed_pane_id_reads_claim(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    claims = tmp_path / "claims"
    claims.mkdir()
    (claims / "win-codex-ws.json").write_text('{"pane_id": "%31", "ts": 1793680000}')
    assert detect.claimed_pane_id("/mnt/c/Users/user-a/win-codex-ws") == "%31"
    assert detect.claimed_pane_id("/nowhere/else") == ""


def test_current_pane_id_claim_beats_stale_environ(monkeypatch, tmp_path):
    monkeypatch.setenv("A2A_MAILBOX_ROOT", str(tmp_path))
    monkeypatch.delenv("TMUX_PANE", raising=False)
    claims = tmp_path / "claims"
    claims.mkdir()
    (claims / "ws.json").write_text('{"pane_id": "%40", "ts": 2}')
    monkeypatch.setattr(detect.os, "getcwd", lambda: "/proj/ws")
    monkeypatch.setattr(detect, "environ_pane_of", lambda pid: "%14" if pid == 20 else "")
    parents = {10: 20, 20: 1}
    monkeypatch.setattr(detect.os, "getpid", lambda: 10)
    monkeypatch.setattr(detect, "ppid_of", lambda pid: parents.get(pid, 0))
    assert detect.current_pane_id() == "%40"


def test_cgnat_regex_matches_only_100_64_10():
    sample = "inet 100.101.0.26/32 brd 100.101.0.26 scope global eth1\ninet 100.160.0.1/32 scope global"
    matched = detect.CGNAT_INET_RE.search(sample)
    assert matched is not None
    assert "100.101.0.26" in matched.group(0)
    assert detect.CGNAT_INET_RE.search("inet 100.63.0.1/32") is None
    assert detect.CGNAT_INET_RE.search("inet 100.128.0.1/32") is None
    assert detect.CGNAT_INET_RE.search("inet 192.168.1.1/24") is None




def test_pane_id_from_listing_matches_ancestor():
    listing = "%3 400\n%16 2702127\n%9 999\n"
    assert detect.pane_id_from_listing(listing, {2702127, 2703000}) == "%16"


def test_pane_id_from_listing_returns_empty_without_match():
    assert detect.pane_id_from_listing("%3 400\n", {1}) == ""


def test_current_pane_id_prefers_env(monkeypatch):
    monkeypatch.setenv("TMUX_PANE", "%42")
    assert detect.current_pane_id() == "%42"


def test_current_pane_id_explicit_override_wins(monkeypatch):
    monkeypatch.setenv("A2A_PANE_ID", "%26")
    monkeypatch.setenv("TMUX_PANE", "%42")
    assert detect.current_pane_id() == "%26"


def test_current_pane_id_bridge_alias_decl_is_paneless(monkeypatch):
    monkeypatch.setenv("TMUX_PANE", "%42")
    monkeypatch.setenv("A2A_SSH_ALIAS", "host-b")
    assert detect.current_pane_id() == ""


def test_detect_cli_env_override_wins(monkeypatch):
    monkeypatch.setenv("A2A_CLI", "codex")
    comm_reader, cmdline_reader, ppid_reader = fake_chain(
        {10: "python3", 20: "claude"},
        {10: 20, 20: 1},
    )
    assert detect.detect_cli(pid=10, comm_reader=comm_reader, cmdline_reader=cmdline_reader, ppid_reader=ppid_reader) == "codex"


def test_current_pane_id_recovers_pane_from_ancestor_environ(monkeypatch):
    monkeypatch.delenv("TMUX_PANE", raising=False)
    parents = {10: 20, 20: 1}
    monkeypatch.setattr(detect.os, "getpid", lambda: 10)
    monkeypatch.setattr(detect, "ppid_of", lambda pid: parents.get(pid, 0))
    monkeypatch.setattr(detect, "environ_pane_of", lambda pid: "%14" if pid == 20 else "")
    assert detect.current_pane_id() == "%14"


def test_current_pane_id_discovers_from_process_tree(monkeypatch):
    monkeypatch.delenv("TMUX_PANE", raising=False)
    listing = "%3 400\n%16 2702127\n"
    parents = {10: 2702127, 2702127: 1}
    monkeypatch.setattr(detect.os, "getpid", lambda: 10)
    monkeypatch.setattr(detect, "ppid_of", lambda pid: parents.get(pid, 0))
    monkeypatch.setattr(detect, "environ_pane_of", lambda pid: "")
    monkeypatch.setattr(detect.tmuxio, "run_tmux", lambda args, ssh_host=None: listing)
    assert detect.current_pane_id() == "%16"


def test_paneless_env_forces_empty_pane(monkeypatch):
    for name in ("TMUX_PANE", "A2A_PANE_ID"):
        monkeypatch.setenv(name, "%99")
    assert detect.current_pane_id() == "%99"
    monkeypatch.setattr(detect, "claimed_pane_id", lambda cwd: "%98")
    monkeypatch.setenv("A2A_PANELESS", "1")
    assert detect.current_pane_id() == ""


def test_agent_spec_registry_aggregates():
    from common import agents

    assert set(agents.cli_names()) >= {"claude", "codex", "pi", "zcode"}
    assert agents.delivery_kind("pi") == "native-inbox"
    assert agents.delivery_kind("zcode") == "pull-only"
    assert agents.delivery_kind("claude") == "tmux"
    assert agents.delivery_kind("no-such-cli") == "tmux"
    assert agents.pull_only_clis() == ("zcode",)
    assert "zcode" in detect.KNOWN_CLI_BASENAMES
    assert detect.PULL_ONLY_CLIS == ("zcode",)


def test_local_host_nt_falls_back_without_uname(monkeypatch):
    monkeypatch.setattr(detect.os, "name", "nt")
    monkeypatch.delattr(detect.os, "uname", raising=False)
    monkeypatch.setenv("COMPUTERNAME", "WINLAB")
    assert detect.local_host() == "WINLAB"


def test_local_host_nt_without_computername_uses_socket(monkeypatch):
    monkeypatch.setattr(detect.os, "name", "nt")
    monkeypatch.delattr(detect.os, "uname", raising=False)
    monkeypatch.delenv("COMPUTERNAME", raising=False)
    monkeypatch.setattr(detect.socket, "gethostname", lambda: "SOCKFALLBACK")
    assert detect.local_host() == "SOCKFALLBACK"
