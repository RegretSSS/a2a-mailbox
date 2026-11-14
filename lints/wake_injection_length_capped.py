#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
MSGFMT = ROOT / "common" / "msgfmt.py"
MCP = ROOT / "mcp" / "mailbox_mcp.py"
HUB = ROOT / "hub" / "hub.py"


def lint() -> list[str]:
    problems = []
    source = MSGFMT.read_text()
    if "INJECTION_SAFE_MAX" not in source or "capped_body" not in source:
        return [
            "common/msgfmt.py: compose_wake 缺注入长度防御——CC TUI 2.1.312+ 超长注入(实测 >426 字符)被折叠成 "
            "paste blob, 屏幕不见原文致帧级 echo 判据 miss→误判重注重复消息; 必须 capped_body 截断+mail_read 指引"
        ]
    compose = source.split("def compose_wake", 1)[-1].split("def ", 1)[0]
    if "capped_body(body, msg_id, overhead) if cap_injection else body" not in compose:
        problems.append(
            "common/msgfmt.py: compose_wake 必须按 cap_injection 决定 capped_body——tmux 注入通道截断, "
            "native/queue/rpc 通道(pi steer/codex queue/dsh rpc)不涉输入框, 截断纯粹浪费收件方一轮 mail_read"
        )
    if "cap_injection: bool = True" not in source:
        problems.append("common/msgfmt.py: compose_wake 缺 cap_injection 参数(默认 True 保 tmux 防御)")
    if "utf16_length" not in compose:
        problems.append(
            "common/msgfmt.py: 长度判据必须 utf16_length——TUI 折叠阈值按 JS length(UTF-16 units)判, "
            "Python len() 是 code points, 增补平面字符(emoji)差一倍, 全 emoji 文本 400 字符实际 800 units 超 520 折叠线"
        )
    mcp_source = MCP.read_text()
    if 'cap_injection = bool(agent_specs.spec_for(str(target.get("cli") or "")).get("wake_cap"))' not in mcp_source:
        problems.append(
            "mcp/mailbox_mcp.py: do_send 的 cap 判据必须 spec_for().get('wake_cap')——按通道判(delivery_kind==tmux)会把 "
            "cli 识别失败的档(unknown, 2026-11-13 unknown-host-b-aicontest 实案: codex 被认成 tmux 白截)误伤; "
            "只有实证过 TUI paste 折叠的 cli 才标 wake_cap"
        )
    hub_source = HUB.read_text()
    if "cap_injection=self.wake_cap" not in hub_source:
        problems.append("hub/hub.py: wake_text_resolved 回退合成必须按 Delivery.wake_cap")
    if 'cap_injection=bool(cli_agents.spec_for(str(sender_record.get("cli") or ""))' not in hub_source:
        problems.append("hub/hub.py: bounce 必须按 sender cli 的 spec wake_cap 决定 cap")
    capped_specs = [p for p in sorted((ROOT / "common" / "agents").glob("*.py")) if '"wake_cap"' in p.read_text()]
    if [p.name for p in capped_specs] != ["claude.py"]:
        problems.append(
            f"common/agents/: wake_cap 持有者必须恰好 [claude.py], 实际 {sorted(p.name for p in capped_specs)}——"
            "pi(steer)/codex(queue daemon)/zcode(pull-only)/dsh(rpc) 都不经过输入框, 多标即白截"
        )
    from common import msgfmt

    long_body = "长" * 600
    uncapped = msgfmt.compose_wake("claude-a", "6b5248d36385", long_body, cap_injection=False)
    if "超长截断" in uncapped or "长" * 600 not in uncapped:
        problems.append("behavioral: cap_injection=False 超长 body 必须全文直过, 不得截断")
    capped = msgfmt.compose_wake("claude-a", "6b5248d36385", long_body)
    if "超长截断" not in capped:
        problems.append("behavioral: 默认 cap_injection=True 的 tmux 防御回归失效")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
