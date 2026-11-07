import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

DAEMON_PID_RELPATH = ("app-server-daemon", "daemon.pid")
THREAD_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
QUEUE_TIMEOUT_SECONDS = 20.0


def default_codex_home() -> Path:
    override = os.environ.get("CODEX_HOME", "")
    if override:
        return Path(override)
    return Path.home() / ".codex"


def daemon_pid_path(codex_home: Path) -> Path:
    return Path(codex_home).joinpath(*DAEMON_PID_RELPATH)


def parse_daemon_pid(payload: str) -> int:
    stripped = payload.strip()
    if stripped.startswith("{"):
        try:
            return int(json.loads(stripped).get("pid") or 0)
        except ValueError:
            return 0
    try:
        return int(stripped.split()[0])
    except (ValueError, IndexError):
        return 0


def daemon_alive(codex_home: Path) -> bool:
    try:
        payload = daemon_pid_path(codex_home).read_text().strip()
    except OSError:
        return False
    pid = parse_daemon_pid(payload)
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def read_cmdline(pid: int) -> list[str]:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return []
    return [part for part in raw.decode("utf-8", errors="replace").split("\0") if part]


def basename(value: str) -> str:
    return value.rstrip("/").rsplit("/", 1)[-1]


def thread_of_argv(argv: list[str]) -> str:
    for arg in reversed(argv):
        if basename(arg) == "codex":
            continue
        matched = THREAD_RE.search(arg)
        if matched:
            return matched.group(0)
    return ""


def thread_of_pid(pid: int) -> str:
    argv = read_cmdline(pid)
    if not argv or basename(argv[0]) != "codex":
        return ""
    return thread_of_argv(argv)


def locate_tui(cwd: str, timeout: float = 3.0) -> dict:
    try:
        listing = subprocess.run(
            ["tmux", "list-panes", "-a", "-F", "#{pane_id}?#{pane_pid}?#{pane_current_path}"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if listing.returncode != 0:
        return {}
    found: list[dict] = []
    for line in listing.stdout.splitlines():
        fields = line.split("?")
        if len(fields) != 3:
            continue
        pane_id, raw_pid, pane_path = fields
        if pane_path != cwd or not raw_pid.isdigit():
            continue
        argv = read_cmdline(int(raw_pid))
        if not argv or basename(argv[0]) != "codex":
            continue
        found.append({"pane_id": pane_id, "pane_pid": raw_pid, "thread": thread_of_argv(argv)})
    return found[0] if len(found) == 1 else {}


def thread_from_ancestors(pid: int | None = None, limit: int = 64) -> str:
    current = os.getpid() if pid is None else pid
    seen: set[int] = set()
    for _ in range(limit):
        if current <= 1 or current in seen:
            break
        seen.add(current)
        thread = thread_of_pid(current)
        if thread:
            return thread
        try:
            with open(f"/proc/{current}/stat") as handle:
                current = int(handle.read().split(")")[-1].split()[1])
        except (OSError, ValueError, IndexError):
            break
    return ""


WIN_CWD_RE = re.compile(r"^/mnt/([a-z])/", re.IGNORECASE)
WIN_DRIVE_CWD_RE = re.compile(r"^([a-z]):[\\/](.*)$", re.IGNORECASE)
SESSION_ID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def locate_win(cwd: str, users_root: Path | None = None) -> dict:
    win_cwd = ""
    posix_match = WIN_CWD_RE.match(cwd or "")
    native_match = WIN_DRIVE_CWD_RE.match(cwd or "")
    if posix_match:
        win_cwd = posix_match.group(1).upper() + ":\\" + cwd[7:].replace("/", "\\")
    elif native_match:
        win_cwd = native_match.group(1).upper() + ":\\" + native_match.group(2).replace("/", "\\")
    else:
        return {}
    users = users_root
    if users is None:
        users = Path.home().parent if os.name == "nt" else Path("/mnt/c/Users")
    if not users.is_dir():
        return {}
    needle = ('"cwd":"' + win_cwd.replace("\\", "\\\\") + '"').lower()
    candidates = []
    for profile in sorted(users.iterdir()):
        try:
            home = profile / ".codex"
            if not (home / "sessions").is_dir():
                continue
            bins = sorted(
                profile.glob("AppData/Local/OpenAI/Codex/bin/*/codex.exe"),
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            )
            if not bins:
                continue
            rollouts = sorted(
                home.glob("sessions/**/*.jsonl"),
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            )
            for rollout in rollouts[:24]:
                session_ids = SESSION_ID_RE.findall(rollout.name)
                if not session_ids:
                    continue
                try:
                    head = rollout.open("r", errors="replace").read(8192).lower()
                except OSError:
                    continue
                if needle in head:
                    candidates.append((rollout.stat().st_mtime, str(bins[0]), str(home), session_ids[0]))
        except OSError:
            continue
    if not candidates:
        return {}
    _, codex_bin, codex_home, codex_thread = max(candidates)
    return {"codex_bin": codex_bin, "codex_home": codex_home, "codex_thread": codex_thread}


def parse_queued_message(output: str) -> str:
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("Queued message "):
            parts = stripped.split()
            if len(parts) >= 3:
                return parts[2]
    return ""


def is_windows_bin(codex_bin: str) -> bool:
    return codex_bin.rstrip("/").lower().endswith(".exe")


def anchors_complete(record: dict) -> bool:
    return (
        bool(str(record.get("codex_bin") or ""))
        and bool(str(record.get("codex_home") or ""))
        and bool(str(record.get("codex_thread") or ""))
    )


def enqueue_async(codex_bin: str, codex_home: Path, thread_id: str, message: str):
    handle = tempfile.NamedTemporaryFile(prefix="a2a-codexq-", suffix=".out", delete=False)
    env = dict(os.environ)
    if not is_windows_bin(codex_bin):
        env["CODEX_HOME"] = str(codex_home)
    try:
        proc = subprocess.Popen(
            [codex_bin, "queue", "--thread", thread_id, "--message", message],
            stdout=handle,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            env=env,
        )
    except OSError:
        handle.close()
        os.unlink(handle.name)
        return None, ""
    return proc, handle.name


def read_output(path: str) -> str:
    try:
        return Path(path).read_text(errors="replace")
    except OSError:
        return ""
