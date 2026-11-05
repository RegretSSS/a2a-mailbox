#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def lint() -> list[str]:
    problems = []
    source = (ROOT / "mcp" / "mailbox_mcp.py").read_text()
    dispatcher = re.search(r"def do_group\(.*?\n(.*?)(?=\ndef |\n@mcp|\Z)", source, re.S)
    dispatched = set(re.findall(r"\b(do_\w+)\(", dispatcher.group(1))) if dispatcher else set()
    for verb in sorted(set(re.findall(r"^def (do_\w+)\(", source, re.M))):
        wrapper = f"mail_{verb[3:]}"
        if f"@mcp.tool()\ndef {wrapper}(" in source:
            continue
        if verb in dispatched:
            continue
        problems.append(
            f"mcp/mailbox_mcp.py: {verb} 存在但既无同名 @mcp.tool() 包装 def {wrapper} 也未被 do_group 调度——接收方可调的动词必须可达(默认面≤6, 群组动作走 mail_group)"
        )
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
