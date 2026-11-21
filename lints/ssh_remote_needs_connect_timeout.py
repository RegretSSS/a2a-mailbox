#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = ("common/tmuxio.py", "common/sshio.py", "hub/hub.py", "mcp/mailbox_mcp.py")


def lint() -> list[str]:
    problems = []
    sshio_src = (ROOT / "common" / "sshio.py").read_text()
    if 'SSH_CONNECT_OPTIONS = ("-o", "BatchMode=yes", "-o", "ConnectTimeout=3")' not in sshio_src:
        problems.append("common/sshio.py: SSH_CONNECT_OPTIONS 必须固定含 BatchMode+ConnectTimeout=3——抽出的统一 ssh 入口丢参数即全线裸奔")
    for rel in TARGETS:
        path = ROOT / rel
        lines = path.read_text().splitlines()
        for index, line in enumerate(lines, start=1):
            if '"ssh"' not in line and "'ssh'" not in line:
                continue
            if "ssh_argv" in line or "SSH_CONNECT_OPTIONS" in line:
                continue
            window = "\n".join(lines[index - 1 : index + 3])
            if "ConnectTimeout" not in window:
                problems.append(
                    f"{rel}:{index}: ssh 构造缺 ConnectTimeout——远端网络间歇时挂内核 SYN 超时,"
                    f" sweep/refresh_display 里的探测会阻塞 hub 主循环 tick 数十秒: {line.strip()}"
                )
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
