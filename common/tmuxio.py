import shlex
import subprocess
import time

CLEAR_INPUT_SETTLE_SECONDS = 0.3
PASTE_DIGEST_SECONDS = 1.2
CLEAR_BACKSPACES = 1200
BSPACE_KEYS = ("BSpace",) * CLEAR_BACKSPACES
TMUX_TIMEOUT_SECONDS = 8.0
BUSY_PROBE_SPAN_SECONDS = 0.6
BUSY_PROBE_LINES = 6
QUIET_MARK = "@a2a_quiet"
ENTER_QUIET_LADDER = (0.5, 1.5)
ENTER_SETTLE_LADDER = (0.3, 2.5, 8.0)
SSH_MUX_OPTIONS = (
    "-o",
    "ControlMaster=auto",
    "-o",
    "ControlPath=/tmp/a2a-ssh-%C",
    "-o",
    "ControlPersist=60",
)


def tmux_command(args, ssh_host: str | None = None) -> list[str]:
    if ssh_host:
        return [
            "ssh",
            *SSH_MUX_OPTIONS,
            "-o",
            "ConnectTimeout=3",
            ssh_host,
            shlex.join(["tmux", *args]),
        ]
    return ["tmux", *args]


def run_tmux(args, ssh_host: str | None = None) -> str:
    try:
        finished = subprocess.run(
            tmux_command(args, ssh_host),
            capture_output=True,
            text=True,
            timeout=TMUX_TIMEOUT_SECONDS,
        )
        return finished.stdout
    except Exception:
        return ""


def respawn_window(slot: str, command: list[str]) -> bool:
    try:
        finished = subprocess.run(
            tmux_command(["respawn-window", "-k", "-t", slot, *command], None),
            capture_output=True,
            text=True,
            timeout=TMUX_TIMEOUT_SECONDS,
        )
    except Exception:
        return False
    return finished.returncode == 0


def recreate_window(slot: str, cwd: str, command: list[str]) -> bool:
    session, marker, window = slot.partition(":")
    if not marker or not session or not window:
        return False
    args = ["new-window", "-t", session, "-n", window]
    if cwd:
        args += ["-c", cwd]
    try:
        finished = subprocess.run(
            tmux_command([*args, *command], None),
            capture_output=True,
            text=True,
            timeout=TMUX_TIMEOUT_SECONDS,
        )
    except Exception:
        return False
    return finished.returncode == 0


def pane_pid(pane_id: str, ssh_host: str | None = None) -> str:
    return run_tmux(("display-message", "-p", "-t", pane_id, "#{pane_pid}"), ssh_host).strip()


def pane_window_name(pane_id: str, ssh_host: str | None = None) -> str:
    return run_tmux(("display-message", "-p", "-t", pane_id, "#{window_name}"), ssh_host).strip()


def pane_slot(pane_id: str, ssh_host: str | None = None) -> str:
    return run_tmux(
        ("display-message", "-p", "-t", pane_id, "#{session_name}:#{window_name}"), ssh_host
    ).strip()


def slot_pane_id(slot: str, ssh_host: str | None = None) -> str:
    return run_tmux(("display-message", "-p", "-t", slot, "#{pane_id}"), ssh_host).strip()


def pane_current_command(pane_id: str, ssh_host: str | None = None) -> str:
    return run_tmux(("display-message", "-p", "-t", pane_id, "#{pane_current_command}"), ssh_host).strip()


PANE_SNAPSHOT_FORMAT = "#{pane_id}\t#{pane_pid}\t#{session_name}:#{window_name}\t#{pane_created}\t#{pane_current_path}\t#{pane_current_command}"


def snapshot_all_panes(ssh_host: str | None = None) -> dict:
    text = run_tmux(("list-panes", "-a", "-F", PANE_SNAPSHOT_FORMAT), ssh_host)
    panes = {}
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) != 6:
            continue
        panes[parts[0]] = {
            "pane_pid": parts[1],
            "slot": parts[2],
            "pane_created": parts[3],
            "cwd": parts[4],
            "command": parts[5],
        }
    return panes


def pane_pid_matches(pane_id: str, expected_pid: str, ssh_host: str | None = None) -> bool:
    if not pane_id or not expected_pid:
        return False
    return pane_pid(pane_id, ssh_host) == str(expected_pid)


def send_literal(pane_id: str, text: str, ssh_host: str | None = None) -> None:
    run_tmux(("send-keys", "-t", pane_id, "-l", text), ssh_host)


def send_enter(pane_id: str, ssh_host: str | None = None) -> None:
    run_tmux(("send-keys", "-t", pane_id, "Enter"), ssh_host)


def clear_input(pane_id: str, ssh_host: str | None = None) -> None:
    run_tmux(("send-keys", "-t", pane_id, *BSPACE_KEYS), ssh_host)
    time.sleep(CLEAR_INPUT_SETTLE_SECONDS)


def stage_buffer(text: str, ssh_host: str | None = None) -> None:
    try:
        subprocess.run(
            tmux_command(("load-buffer", "-"), ssh_host),
            input=text,
            capture_output=True,
            text=True,
            timeout=TMUX_TIMEOUT_SECONDS,
        )
    except Exception:
        return


def paste_bracketed(pane_id: str, text: str, ssh_host: str | None = None) -> None:
    stage_buffer(text, ssh_host)
    run_tmux(("paste-buffer", "-p", "-t", pane_id), ssh_host)


def inject_wake(pane_id: str, wake_text: str, ssh_host: str | None = None) -> None:
    clear_input(pane_id, ssh_host)
    if "\n" in wake_text:
        paste_bracketed(pane_id, wake_text, ssh_host)
    else:
        send_literal(pane_id, wake_text, ssh_host)
    for settle in ENTER_SETTLE_LADDER:
        time.sleep(settle)
        send_enter(pane_id, ssh_host)


def prime_injection(pane_id: str, wake_text: str, ssh_host: str | None = None) -> None:
    clear_input(pane_id, ssh_host)
    if "\n" in wake_text:
        paste_bracketed(pane_id, wake_text, ssh_host)
    else:
        send_literal(pane_id, wake_text, ssh_host)
    time.sleep(PASTE_DIGEST_SECONDS)
    send_enter(pane_id, ssh_host)


def pane_created(pane_id: str, ssh_host: str | None = None) -> float:
    text = run_tmux(("display-message", "-p", "-t", pane_id, "#{pane_created}"), ssh_host).strip()
    try:
        return float(text)
    except ValueError:
        return 0.0


def capture_bottom(pane_id: str, line_count: int = 10, ssh_host: str | None = None) -> str:
    frame = run_tmux(("capture-pane", "-p", "-t", pane_id, "-S", "0"), ssh_host)
    return "\n".join(frame.rstrip("\n").split("\n")[-line_count:])


def capture_joined_bottom(pane_id: str, line_count: int = 60, ssh_host: str | None = None) -> str:
    frame = run_tmux(("capture-pane", "-p", "-J", "-t", pane_id, "-S", "0"), ssh_host)
    return "\n".join(frame.rstrip("\n").split("\n")[-line_count:])


def quiet_mark(pane_id: str, ssh_host: str | None = None) -> str:
    return run_tmux(("show-options", "-p", "-v", "-t", pane_id, QUIET_MARK), ssh_host).strip()


def pane_busy(pane_id: str, ssh_host: str | None = None) -> bool:
    first = capture_bottom(pane_id, BUSY_PROBE_LINES, ssh_host)
    time.sleep(BUSY_PROBE_SPAN_SECONDS)
    second = capture_bottom(pane_id, BUSY_PROBE_LINES, ssh_host)
    return frames_show_growth(first, second)


def frames_show_growth(first: str, second: str) -> bool:
    a_lines = first.rstrip("\n").split("\n")
    b_lines = second.rstrip("\n").split("\n")
    if not a_lines or not b_lines:
        return False
    changed = [
        (a_line, b_line)
        for a_line, b_line in zip(a_lines, b_lines)
        if a_line != b_line
    ]
    if not changed:
        return False
    if len(changed) >= 2:
        return True
    a_line, b_line = changed[0]
    return a_line.startswith(b_line) or b_line.startswith(a_line)


def command_forms(pane_id: str, ssh_host: str | None = None) -> list[tuple[str, list[str], str]]:
    return [
        ("liveness", tmux_command(("display-message", "-p", "-t", pane_id, "#{pane_pid}"), ssh_host), ""),
        ("clear_input", tmux_command(("send-keys", "-t", pane_id, *BSPACE_KEYS), ssh_host), ""),
        ("stage_buffer", tmux_command(("load-buffer", "-"), ssh_host), "wake_text via stdin"),
        ("paste_bracketed", tmux_command(("paste-buffer", "-p", "-t", pane_id), ssh_host), ""),
        ("send_enter", tmux_command(("send-keys", "-t", pane_id, "Enter"), ssh_host), ""),
        ("capture_bottom", tmux_command(("capture-pane", "-p", "-t", pane_id, "-S", "0"), ssh_host), ""),
    ]
