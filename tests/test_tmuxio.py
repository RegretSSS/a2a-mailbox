import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import tmuxio






def test_pane_pid_matches_requires_both_fields():
    assert not tmuxio.pane_pid_matches("", "100")
    assert not tmuxio.pane_pid_matches("%1", "")


def test_bspace_keys_hoisted_tuple():
    assert len(tmuxio.BSPACE_KEYS) == tmuxio.CLEAR_BACKSPACES
    assert tmuxio.BSPACE_KEYS[0] == "BSpace"
    assert isinstance(tmuxio.BSPACE_KEYS, tuple)


def test_tmux_command_local_and_ssh_forms():
    assert tmuxio.tmux_command(("send-keys", "-t", "%1", "-l", "x")) == [
        "tmux", "send-keys", "-t", "%1", "-l", "x",
    ]
    assert tmuxio.tmux_command(("display-message", "-p", "-t", "%9", "#{pane_pid}"), "host-b") == [
        "ssh", "-o", "ControlMaster=auto", "-o", "ControlPath=/tmp/a2a-ssh-%C", "-o", "ControlPersist=3600", "-o", "ConnectTimeout=3", "host-b", "tmux display-message -p -t %9 '#{pane_pid}'",
    ]


def test_run_tmux_passes_ssh_prefix(monkeypatch):
    seen = {}

    class Finished:
        stdout = "ok"

    def fake_run(command, **kwargs):
        seen["command"] = command
        return Finished()

    monkeypatch.setattr(tmuxio.subprocess, "run", fake_run)
    tmuxio.run_tmux(("display-message",), "100.5.5.5")
    assert seen["command"] == ["ssh", "-o", "ControlMaster=auto", "-o", "ControlPath=/tmp/a2a-ssh-%C", "-o", "ControlPersist=3600", "-o", "ConnectTimeout=3", "100.5.5.5", "tmux display-message"]


def test_frames_show_growth_still_pane_is_idle():
    frame = "line1\nline2\nline3"
    assert not tmuxio.frames_show_growth(frame, frame)


def test_frames_show_growth_typing_appends():
    assert tmuxio.frames_show_growth("a\nb\n草稿", "a\nb\n草稿继续")


def test_frames_show_growth_backspace_counts():
    assert tmuxio.frames_show_growth("a\nb\n草稿", "a\nb\n草")


def test_frames_show_growth_scrolling_output_counts():
    assert tmuxio.frames_show_growth("old1\nold2\nx", "old2\nx\nnew")


def test_frames_show_growth_in_place_spinner_is_idle():
    assert not tmuxio.frames_show_growth("a\n⠋ working", "a\n⠙ working")


def test_frame_grew_since_probes_without_sleep(monkeypatch):
    frames = ["a\n草稿x"]

    def fake_capture(pane, line_count=10, ssh_host=None):
        return frames.pop(0)

    monkeypatch.setattr(tmuxio, "capture_bottom", fake_capture)
    monkeypatch.setattr(tmuxio.time, "sleep", lambda seconds: (_ for _ in ()).throw(AssertionError("busy 探测不得阻塞 sleep")))
    assert tmuxio.frame_grew_since("a\n草稿", "%3")


def test_quiet_mark_reads_pane_option(monkeypatch):
    seen = {}

    def fake_run_tmux(args, ssh_host=None):
        seen["args"] = args
        return "1\n"

    monkeypatch.setattr(tmuxio, "run_tmux", fake_run_tmux)
    assert tmuxio.quiet_mark("%3") == "1"
    assert seen["args"] == ("show-options", "-p", "-v", "-t", "%3", tmuxio.QUIET_MARK)
