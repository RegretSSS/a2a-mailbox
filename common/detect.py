import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from common import agents as agent_specs
from common import paths, tmuxio

KNOWN_CLI_BASENAMES = agent_specs.proc_names()
PULL_ONLY_CLIS = agent_specs.pull_only_clis()
PROC_WALK_LIMIT = 64
CLI_ENV_OVERRIDE = "A2A_CLI"
PANELESS_ENV = "A2A_PANELESS"
PANE_ENV_OVERRIDES = ("A2A_PANE_ID", "TMUX_PANE")
HOST_ALIAS_ENV = "A2A_SSH_ALIAS"
HOST_TAG_ENV = "A2A_HOST_TAG"
AGENT_ID_ENV = "A2A_AGENT_ID"
HOST_TAG_FILE = "host_tag"
TS_STATUS_COMMANDS = (
    ("tailscale",),
    ("bash", "-c", '"/mnt/c/Program Files/Tailscale/tailscale.exe" status --json'),
)
CGNAT_INET_RE = re.compile(
    r"inet 100\.(?:6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\.[0-9]+\.[0-9]+"
)
QUALIFIER_RE = re.compile(r"[^a-z0-9-]+")

TS_SELF_CACHE: str | None = None


def basename_of(value: str) -> str:
    return value.rstrip("/").rsplit("/", 1)[-1]


def comm_of(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/comm").read_text().strip()
    except OSError:
        return ""


def cmdline0_of(pid: int) -> str:
    try:
        fields = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    except OSError:
        return ""
    return fields[0].decode("utf-8", "ignore") if fields else ""


def ppid_of(pid: int) -> int:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("PPid:"):
                return int(line.split()[1])
    except (OSError, ValueError):
        pass
    return 0


def detect_cli(
    pid: int | None = None,
    comm_reader=comm_of,
    cmdline_reader=cmdline0_of,
    ppid_reader=ppid_of,
) -> str:
    override = os.environ.get(CLI_ENV_OVERRIDE, "")
    if override:
        return override
    current = os.getpid() if pid is None else pid
    for _ in range(PROC_WALK_LIMIT):
        if current <= 1:
            break
        for name in (comm_reader(current), basename_of(cmdline_reader(current))):
            if name in KNOWN_CLI_BASENAMES:
                return name
        current = ppid_reader(current)
    return "unknown"


def ancestor_pid_set(pid: int | None = None, ppid_reader=ppid_of) -> set[int]:
    current = os.getpid() if pid is None else pid
    ancestors = set()
    for _ in range(PROC_WALK_LIMIT):
        if current <= 1:
            break
        ancestors.add(current)
        current = ppid_reader(current)
    return ancestors


def pane_id_from_listing(panes_listing: str, ancestors: set[int]) -> str:
    for line in panes_listing.splitlines():
        pane_id, _, pane_pid_text = line.partition(" ")
        if pane_pid_text.strip().isdigit() and int(pane_pid_text) in ancestors:
            return pane_id
    return ""


def environ_pane_of(pid: int) -> str:
    try:
        raw = Path(f"/proc/{pid}/environ").read_bytes()
    except OSError:
        return ""
    for entry in raw.split(b"\0"):
        if entry.startswith(b"TMUX_PANE="):
            return entry.decode("utf-8", "ignore").split("=", 1)[1]
    return ""


def current_pane_id(env_pane: str | None = None) -> str:
    if env_pane is not None:
        return env_pane
    if os.environ.get(PANELESS_ENV) or os.environ.get(HOST_ALIAS_ENV):
        return ""
    for name in PANE_ENV_OVERRIDES:
        override = os.environ.get(name, "")
        if override:
            return override
    claimed = claimed_pane_id(os.getcwd())
    if claimed:
        return claimed
    current = os.getpid()
    ancestors = set()
    for _ in range(PROC_WALK_LIMIT):
        if current <= 1 or current in ancestors:
            break
        ancestors.add(current)
        from_environ = environ_pane_of(current)
        if from_environ:
            return from_environ
        current = ppid_of(current)
    panes_listing = tmuxio.run_tmux(("list-panes", "-a", "-F", "#{pane_id} #{pane_pid}"))
    return pane_id_from_listing(panes_listing, ancestors)


def local_host() -> str:
    return os.uname().nodename


def tailnet_host() -> str:
    binary = shutil.which("tailscale")
    if binary:
        try:
            out = subprocess.run(
                [binary, "ip", "-4"], capture_output=True, text=True, timeout=5
            ).stdout.strip()
            if out:
                return out.splitlines()[0]
        except Exception:
            pass
    try:
        out = subprocess.run(
            ["ip", "-4", "addr"], capture_output=True, text=True, timeout=5
        ).stdout
        matched = CGNAT_INET_RE.search(out)
        if matched:
            return matched.group(0).split()[1]
    except Exception:
        pass
    return ""


def workspace_slug(workspace_dir: str) -> str:
    base = workspace_dir.rstrip("/").rsplit("/", 1)[-1] or "root"
    return re.sub(r"[^a-z0-9-]", "-", base.lower())


def slugify_qualifier(value: str) -> str:
    return QUALIFIER_RE.sub("-", value.lower()).strip("-")


def tailscale_self_name() -> str:
    global TS_SELF_CACHE
    if TS_SELF_CACHE is not None:
        return TS_SELF_CACHE
    TS_SELF_CACHE = ""
    for command in TS_STATUS_COMMANDS:
        try:
            finished = subprocess.run(
                [*command, "status", "--json"], capture_output=True, text=True, timeout=5
            )
            self_node = json.loads(finished.stdout).get("Self") or {}
        except Exception:
            continue
        dns_label = (self_node.get("DNSName") or "").split(".")[0]
        slug = slugify_qualifier(dns_label or self_node.get("HostName") or "")
        if slug:
            TS_SELF_CACHE = slug
            break
    return TS_SELF_CACHE


def host_tag_cache_path() -> Path:
    return paths.mailbox_root() / HOST_TAG_FILE


def read_host_tag_cache() -> str:
    try:
        return slugify_qualifier(host_tag_cache_path().read_text())
    except OSError:
        return ""


def write_host_tag_cache(tag: str) -> None:
    try:
        host_tag_cache_path().parent.mkdir(parents=True, exist_ok=True)
        host_tag_cache_path().write_text(tag)
    except OSError:
        pass


def host_qualifier() -> str:
    for name in (HOST_TAG_ENV, HOST_ALIAS_ENV):
        tagged = os.environ.get(name, "")
        if tagged:
            return slugify_qualifier(tagged) or "host"
    cached = read_host_tag_cache()
    if cached:
        return cached
    ts_name = tailscale_self_name()
    if ts_name:
        write_host_tag_cache(ts_name)
        return ts_name
    return local_host().split(".")[0] or "host"


def build_agent_id(cli: str, workspace_dir: str) -> str:
    explicit = os.environ.get(AGENT_ID_ENV, "").strip()
    if explicit:
        return explicit
    return f"{cli}-{host_qualifier()}-{workspace_slug(workspace_dir)}"


def claimed_pane_id(workspace_dir: str) -> str:
    claim = paths.mailbox_root() / paths.CLAIMS_DIR / f"{workspace_slug(workspace_dir)}.json"
    try:
        payload = json.loads(claim.read_text())
    except (OSError, ValueError):
        return ""
    return str(payload.get("pane_id") or "")
