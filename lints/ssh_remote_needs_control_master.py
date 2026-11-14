#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = ("common/tmuxio.py", "common/sshio.py", "hub/hub.py", "mcp/mailbox_mcp.py")


def lint() -> list[str]:
    problems = []
    mux_source = (ROOT / "common/tmuxio.py").read_text()
    mux_definition = mux_source[mux_source.find("SSH_MUX_OPTIONS") : mux_source.find("SSH_MUX_OPTIONS") + 200]
    if "ControlMaster" not in mux_definition or "ControlPersist" not in mux_definition:
        problems.append("common/tmuxio.py: SSH_MUX_OPTIONS 定义缺 ControlMaster/ControlPersist")
    for rel in TARGETS:
        lines = (ROOT / rel).read_text().splitlines()
        for index, line in enumerate(lines, start=1):
            if '"ssh"' not in line and "'ssh'" not in line:
                continue
            window = "\n".join(lines[max(0, index - 6) : index + 3])
            if "ControlMaster" not in window and "SSH_MUX_OPTIONS" not in window:
                problems.append(
                    f"{rel}:{index}: ssh 构造缺 ControlMaster 复用——tailnet 每次握手 0.2-0.5s,"
                    f" sweep/echo/ack 高频探测会把它放大成主循环地板: {line.strip()}"
                )
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
