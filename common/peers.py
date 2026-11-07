import json
from pathlib import Path

PEERS_FILE = "peers.json"


def peers_path(root: Path) -> Path:
    return root / PEERS_FILE


def load_peers(root: Path) -> list[str]:
    try:
        payload = json.loads(peers_path(root).read_text())
    except (OSError, ValueError):
        return []
    aliases = payload.get("peers", [])
    return [str(alias) for alias in aliases if str(alias)]


def add_peer(root: Path, alias: str) -> bool:
    if alias in load_peers(root):
        return False
    payload = {"peers": [*load_peers(root), alias]}
    peers_path(root).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return True
