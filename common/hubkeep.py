import os
import subprocess
import sys
import time
from pathlib import Path

HUB_SCRIPT = Path(__file__).resolve().parent.parent / "hub" / "hub.py"
SYSTEMD_UNIT = "a2a-hub"
SPAWN_SETTLE_SECONDS = 1.5


def hub_pids() -> list[int]:
    mine = os.getpid()
    found: list[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid == mine:
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        joined = b" ".join(cmdline).decode("utf-8", "replace")
        if "hub/hub.py" in joined and "python" in joined:
            found.append(pid)
    return found


def _systemctl(args: list[str]) -> int | None:
    try:
        finished = subprocess.run(
            ["systemctl", "--user", *args],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return finished.returncode


def ensure_hub_running() -> bool:
    if hub_pids():
        return True
    if _systemctl(["cat", SYSTEMD_UNIT, "--quiet"]) == 0:
        _systemctl(["start", SYSTEMD_UNIT])
        time.sleep(SPAWN_SETTLE_SECONDS)
        if _systemctl(["is-active", "--quiet", SYSTEMD_UNIT]) == 0:
            return True
    subprocess.Popen(
        [sys.executable, str(HUB_SCRIPT)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )
    time.sleep(SPAWN_SETTLE_SECONDS)
    return bool(hub_pids())
