import os
from pathlib import Path

REGISTRY_FILE = "registry.json"
REGISTRY_LOCK = "registry.lock"
QUEUE_DIR = "queue"
HISTORY_DIR = "history"
ACKS_DIR = "acks"
RATES_DIR = "rates"
CLAIMS_DIR = "claims"
NATIVE_DIR = "native-inbox"
JOIN_DIR = "join-requests"
LOG_FILE = "hub.log"
HUB_LOCK_FILE = "hub.lock"
ONLINE_FILE = "online.json"
MCP_HEARTBEAT_FILE = "mcp-heartbeat"
FORENSICS_DIR = "forensics"


def mailbox_root() -> Path:
    override = os.environ.get("A2A_MAILBOX_ROOT")
    if override:
        return Path(override)
    return Path.home() / ".agents-mailbox"


def ensure_layout(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for name in (QUEUE_DIR, HISTORY_DIR, ACKS_DIR, RATES_DIR, CLAIMS_DIR, NATIVE_DIR, JOIN_DIR):
        (root / name).mkdir(parents=True, exist_ok=True)
