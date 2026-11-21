#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import federation, paths, peers


def main() -> None:
    parser = argparse.ArgumentParser(description="拉取 peer 主机注册表并合并为远端 agent（ssh_alias 路由）")
    parser.add_argument("--peer", action="append", default=None)
    args = parser.parse_args()
    root = paths.mailbox_root()
    if args.peer:
        results = [federation.pull_peer(root, alias) for alias in args.peer]
    else:
        if not peers.load_peers(root):
            print(json.dumps({"ok": False, "error": f"无 peer（{peers.peers_path(root)} 未配置且未给 --peer）"}))
            return
        results = federation.pull_all(root)
    print(json.dumps({"ok": all(item["ok"] for item in results), "results": results}, ensure_ascii=False))


if __name__ == "__main__":
    main()
