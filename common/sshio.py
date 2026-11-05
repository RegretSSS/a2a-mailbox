import json
import re
import subprocess

from common import tmuxio

REMOTE_TIMEOUT_SECONDS = 8.0
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
REMOTE_OK = "ok"
REMOTE_UNREACHABLE = "unreachable"
REMOTE_NOT_FOUND = "not_found"
REMOTE_BAD_JSON = "bad_json"


def remote_ack_exists(ssh_host: str, ack_id: str, root_dir: str = ".agents-mailbox") -> bool:
    if not SAFE_ID_RE.match(ack_id):
        return False
    command = ["ssh", *tmuxio.SSH_MUX_OPTIONS, "-o", "BatchMode=yes", "-o", "ConnectTimeout=3", ssh_host, "cat", f"{root_dir}/acks/{ack_id}"]
    try:
        finished = subprocess.run(
            command, capture_output=True, text=True, timeout=REMOTE_TIMEOUT_SECONDS
        )
    except Exception:
        return False
    return finished.returncode == 0 and bool(finished.stdout.strip())


def read_remote_json_status(ssh_host: str, relative_path: str) -> tuple[str, dict | None]:
    command = ["ssh", *tmuxio.SSH_MUX_OPTIONS, "-o", "BatchMode=yes", "-o", "ConnectTimeout=3", ssh_host, "cat", relative_path]
    try:
        finished = subprocess.run(
            command, capture_output=True, text=True, timeout=REMOTE_TIMEOUT_SECONDS
        )
    except Exception:
        return (REMOTE_UNREACHABLE, None)
    if finished.returncode == 255:
        return (REMOTE_UNREACHABLE, None)
    if finished.returncode != 0:
        return (REMOTE_NOT_FOUND, None)
    try:
        payload = json.loads(finished.stdout)
    except ValueError:
        return (REMOTE_BAD_JSON, None)
    if not isinstance(payload, dict):
        return (REMOTE_BAD_JSON, None)
    return (REMOTE_OK, payload)


def read_remote_json(ssh_host: str, relative_path: str) -> dict | None:
    return read_remote_json_status(ssh_host, relative_path)[1]


QUEUE_LIST_SCRIPT = (
    "import json, glob\n"
    "for p in glob.glob('.agents-mailbox/queue/*/*.msg'):\n"
    "    try:\n"
    "        d = json.load(open(p))\n"
    "    except Exception:\n"
    "        continue\n"
    "    if isinstance(d, dict):\n"
    "        print(json.dumps(d, ensure_ascii=False))\n"
)


def read_remote_queue_msgs(ssh_host: str) -> tuple[str, list]:
    command = ["ssh", *tmuxio.SSH_MUX_OPTIONS, "-o", "BatchMode=yes", "-o", "ConnectTimeout=3", ssh_host, "python3", "-"]
    try:
        finished = subprocess.run(
            command, capture_output=True, text=True, timeout=REMOTE_TIMEOUT_SECONDS, input=QUEUE_LIST_SCRIPT
        )
    except Exception:
        return (REMOTE_UNREACHABLE, [])
    if finished.returncode == 255:
        return (REMOTE_UNREACHABLE, [])
    if finished.returncode != 0:
        return (REMOTE_NOT_FOUND, [])
    envelopes = []
    for line in finished.stdout.splitlines():
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if isinstance(payload, dict):
            envelopes.append(payload)
    return (REMOTE_OK, envelopes)


def write_remote_envelope(ssh_host: str, envelope: dict) -> str:
    to = str(envelope.get("to") or "")
    msg_id = str(envelope.get("msg_id") or "")
    if not SAFE_ID_RE.match(to) or not SAFE_ID_RE.match(msg_id):
        return REMOTE_BAD_JSON
    payload = json.dumps(envelope, ensure_ascii=False)
    script = (
        "import json, os, tempfile\n"
        f"target = os.path.join('.agents-mailbox', 'queue', {to!r}, {msg_id!r} + '.msg')\n"
        "if os.path.exists(target):\n"
        "    raise SystemExit(0)\n"
        "os.makedirs(os.path.dirname(target), exist_ok=True)\n"
        f"fd, tmp = tempfile.mkstemp(dir=os.path.dirname(target), suffix='.tmp')\n"
        "try:\n"
        "    with os.fdopen(fd, 'w') as handle:\n"
        f"        handle.write({payload!r})\n"
        "    os.replace(tmp, target)\n"
        "except BaseException:\n"
        "    os.unlink(tmp)\n"
        "    raise\n"
    )
    return run_remote_script(ssh_host, script)


def write_remote_join(ssh_host: str, to: str, sender: str, payload: dict) -> str:
    if not SAFE_ID_RE.match(to) or not SAFE_ID_RE.match(sender):
        return REMOTE_BAD_JSON
    body = json.dumps(payload, ensure_ascii=False)
    script = (
        "import os\n"
        f"target = os.path.join('.agents-mailbox', 'join-requests', {to!r}, {sender!r} + '.json')\n"
        "os.makedirs(os.path.dirname(target), exist_ok=True)\n"
        f"open(target, 'w').write({body!r})\n"
    )
    return run_remote_script(ssh_host, script)


def run_remote_script(ssh_host: str, script: str) -> str:
    command = ["ssh", *tmuxio.SSH_MUX_OPTIONS, "-o", "BatchMode=yes", "-o", "ConnectTimeout=3", ssh_host, "python3", "-"]
    try:
        finished = subprocess.run(
            command, capture_output=True, text=True, timeout=REMOTE_TIMEOUT_SECONDS, input=script
        )
    except Exception:
        return REMOTE_UNREACHABLE
    if finished.returncode == 255:
        return REMOTE_UNREACHABLE
    return REMOTE_OK if finished.returncode == 0 else REMOTE_NOT_FOUND
