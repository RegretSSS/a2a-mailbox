#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIRECT_EXE = re.compile(r'\("([^"]*\.exe)"|run\(\["([^"]*\.exe)"')


def lint() -> list[str]:
    problems = []
    detect_source = (ROOT / "common" / "detect.py").read_text()
    for match in DIRECT_EXE.finditer(detect_source):
        problems.append(
            "common/detect.py: MCP server 进程内直 exec Windows .exe 会经 WSL interop 毒化 fastmcp/anyio 的 stdio 事件循环(挂死 initialize, 宿主 CLI 60s 超时杀子进程)——身份必须走 env/磁盘缓存, interop 只许包在 bash -c 兜底里"
        )
    mcp_source = (ROOT / "mcp" / "mailbox_mcp.py").read_text()
    for index, line in enumerate(mcp_source.splitlines(), start=1):
        if ".exe" in line and re.search(r"Popen|subprocess\.run|os\.system|os\.exec", line):
            problems.append(f"mcp/mailbox_mcp.py:{index}: MCP 进程 spawn 调用点出现 .exe——interop 毒化禁区: {line.strip()}")
    boot_body = re.search(r"def hub_boot_command\(.*?\n(.*?)(?=\ndef )", mcp_source, re.S)
    gate = 'os.name != "nt" and any(part.endswith(".exe")'
    if not boot_body or gate not in boot_body.group(1):
        problems.append(
            "mcp/mailbox_mcp.py: hub 自举命令在 POSIX(WSL) 必须显式拒绝 .exe(interop 毒化 stdio 事件循环), 仅 os.name=='nt' 纯 win 节点放行"
        )
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
