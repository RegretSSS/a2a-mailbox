#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def lint() -> list[str]:
    problems = []
    source = (ROOT / "mcp" / "mailbox_mcp.py").read_text()
    if "不属于任何待确认消息" in source:
        problems.append(
            "mcp/mailbox_mcp.py do_ack: 跨主机时 envelope 在发送方主机, 本地找不到就拒绝会让真实接收方永远无法确认——必须自证落盘"
        )
    if "self_attested" not in source:
        problems.append(
            "mcp/mailbox_mcp.py do_ack: 缺 self_attested 降级标记——传输不可见(envelope 驻对端)时的自证落盘路径必须保留并可辨识"
        )
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
