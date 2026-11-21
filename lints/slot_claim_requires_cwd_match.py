#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MCP = ROOT / "mcp" / "mailbox_mcp.py"


def lint() -> list[str]:
    problems = []
    source = MCP.read_text()
    register = source.split("def register_record", 1)[-1].split("def ", 1)[0]
    slot_loop = register.split('for agent_id, held in existing.items():', 1)[-1]
    if 'str(held.get("cwd") or "") != cwd' not in slot_loop.split("raise RuntimeError")[0]:
        problems.append(
            "mcp/mailbox_mcp.py: slot 认领必须加 cwd 一致性闸——窗名是用户可改标签而非身份, "
            "窗序扰动(会话跑错窗/重启 pane 窗名残留)下纯 slot 认领会把 A 项目的 CC 认领进 B 档 "
            "(11-07 实锤: backend CC 在窗名残留 frontend 的窗里注册, SELF 固化成 frontend, "
            "发信署错名+frontend 正身失锚)"
        )
    if "session_proof = session_env_id()" not in register:
        problems.append(
            "mcp/mailbox_mcp.py: 必须有会话证明优先认领(session_proof=session_env_id() 扫 instances)——"
            "CLAUDE_CODE_SESSION_ID 是会话自证, 同会话跨窗搬家应无条件认领原档(比 slot+cwd 更强的证据)"
        )
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
