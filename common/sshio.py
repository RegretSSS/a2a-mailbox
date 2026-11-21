import json
import re
import subprocess

from common import paths, tmuxio

REMOTE_TIMEOUT_SECONDS = 12.0
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
REMOTE_OK = "ok"
REMOTE_UNREACHABLE = "unreachable"
REMOTE_NOT_FOUND = "not_found"
REMOTE_BAD_JSON = "bad_json"


REMOTE_ACK_PRESENT = "present"
REMOTE_ACK_ABSENT = "absent"
REMOTE_ACK_UNREACHABLE = "unreachable"
SSH_CONNECT_OPTIONS = ("-o", "BatchMode=yes", "-o", "ConnectTimeout=3")


def ssh_argv(ssh_host: str, *remote_command: str) -> list[str]:
    return ["ssh", *tmuxio.SSH_MUX_OPTIONS, *SSH_CONNECT_OPTIONS, ssh_host, *remote_command]


def remote_ack_state(ssh_host: str, ack_id: str) -> str:
    if not SAFE_ID_RE.match(ack_id):
        return REMOTE_ACK_ABSENT
    command = ssh_argv(ssh_host, "cat", f".agents-mailbox/{paths.ACKS_DIR}/{ack_id}")
    try:
        finished = subprocess.run(
            command, capture_output=True, text=True, timeout=REMOTE_TIMEOUT_SECONDS
        )
    except Exception:
        return REMOTE_ACK_UNREACHABLE
    if finished.returncode == 255:
        return REMOTE_ACK_UNREACHABLE
    if finished.returncode != 0:
        return REMOTE_ACK_ABSENT
    return REMOTE_ACK_PRESENT if finished.stdout.strip() else REMOTE_ACK_ABSENT


def read_remote_json_status(ssh_host: str, relative_path: str) -> tuple[str, dict | None]:
    command = ssh_argv(ssh_host, "cat", relative_path)
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


FEDERATION_SNAPSHOT_HEAD = (
    "import json, glob, os\n"
    "out = {'registry': None, 'queue': [], 'settled': {}}\n"
    "try:\n"
    "    out['registry'] = json.load(open(%(registry_path)s))\n"
    "except Exception:\n"
    "    pass\n"
    "for p in glob.glob(%(queue_glob)s):\n"
    "    try:\n"
    "        d = json.load(open(p))\n"
    "    except Exception:\n"
    "        continue\n"
    "    if isinstance(d, dict):\n"
    "        out['queue'].append(d)\n"
)

FEDERATION_SNAPSHOT_TAIL = (
    "for mid in %(probe_ids)s:\n"
    "    if os.path.exists('.agents-mailbox/history/' + mid + '.json'):\n"
    "        out['settled'][mid] = 'archived'\n"
    "    elif glob.glob('.agents-mailbox/queue/*/' + mid + '.failed'):\n"
    "        out['settled'][mid] = 'failed'\n"
    "    else:\n"
    "        out['settled'][mid] = 'missing'\n"
    "print(json.dumps(out, ensure_ascii=False))\n"
)


def read_remote_federation_snapshot(ssh_host: str, probe_ids: list) -> tuple[str, dict | None]:
    command = ssh_argv(ssh_host, "python3", "-")
    script = (FEDERATION_SNAPSHOT_HEAD + FEDERATION_SNAPSHOT_TAIL) % {
        "probe_ids": repr(sorted(set(probe_ids))),
        "registry_path": repr(f".agents-mailbox/{paths.REGISTRY_FILE}"),
        "queue_glob": repr(f".agents-mailbox/{paths.QUEUE_DIR}/*/*.msg"),
    }
    try:
        finished = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=REMOTE_TIMEOUT_SECONDS,
            input=script,
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
    command = ssh_argv(ssh_host, "python3", "-")
    try:
        finished = subprocess.run(
            command, capture_output=True, text=True, timeout=REMOTE_TIMEOUT_SECONDS, input=script
        )
    except Exception:
        return REMOTE_UNREACHABLE
    if finished.returncode == 255:
        return REMOTE_UNREACHABLE
    return REMOTE_OK if finished.returncode == 0 else REMOTE_NOT_FOUND
