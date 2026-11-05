#!/usr/bin/env python3
import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import tmuxio


def compact(argv: list[str]) -> str:
    if len(argv) > 10:
        head = " ".join(argv[:8])
        return f"{head} …(+{len(argv) - 8} args)"
    return " ".join(argv)


def main() -> None:
    parser = argparse.ArgumentParser(description="跨主机 ssh 投递 dry-run: 只构造命令并解析 ssh 配置, 不连接远端")
    parser.add_argument("--host", required=True)
    parser.add_argument("--pane", default="%1")
    args = parser.parse_args()

    for name, argv, stdin_note in tmuxio.command_forms(args.pane, args.host):
        print(f"{name}: {compact(argv)}")
        if stdin_note:
            print(f"  stdin: {stdin_note}")

    resolved = subprocess.run(["ssh", "-G", args.host], capture_output=True, text=True, timeout=15)
    print(f"ssh -G {args.host}: exit={resolved.returncode}")
    for line in resolved.stdout.splitlines():
        if line.startswith(("hostname ", "user ", "port ", "proxyjump ")):
            print(f"  {line}")


if __name__ == "__main__":
    main()
