#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = sorted((ROOT / "deploy" / "dsh").glob("dsh-host*.sh"))
PS1_SCRIPTS = sorted((ROOT / "deploy" / "dsh").glob("dsh-host*.ps1"))
PS1_COOKIE_PURGE = r"Remove-Item \$cookiePath"


def lint() -> list[str]:
    problems = []
    for path in SCRIPTS:
        text = path.read_text()
        writes_token = re.search(r'\$\{?agent_id\}?\.token', text)
        if not writes_token:
            continue
        if not re.search(r'rm\s+-f\s+\S*\$\{?agent_id\}?\}?\.cookie', text):
            problems.append(
                f"{path.relative_to(ROOT)}: 写 token 未清旧 cookie——host 重启=新 launch token, "
                "ensure_cookie 对未过期旧 cookie 直接复用, 失配 cookie 最长 27 天投递 401, "
                "起 host 抓到新 token 时必须同步删 <agent_id>.cookie 强制换新"
            )
    for path in PS1_SCRIPTS:
        text = path.read_text()
        if "$AgentId.token" not in text:
            continue
        if not re.search(PS1_COOKIE_PURGE, text):
            problems.append(
                f"{path.relative_to(ROOT)}: 写 token 未清旧 cookie——host 重启=新 launch token, "
                "ensure_cookie 对未过期旧 cookie 直接复用, 失配 cookie 最长 27 天投递 401"
            )
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
