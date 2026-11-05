#!/usr/bin/env python3
import re
import sys
from pathlib import Path

SSH_LIST_WITH_TMUX = re.compile(r'\[\s*"ssh"[^\]]*"tmux"')
ROOT = Path(__file__).resolve().parent.parent


def lint() -> list[str]:
    problems = []
    for py in sorted(ROOT.glob("*/*.py")):
        for number, line in enumerate(py.read_text().splitlines(), 1):
            if SSH_LIST_WITH_TMUX.search(line) and "shlex.join" not in line:
                problems.append(f"{py.relative_to(ROOT)}:{number}: ssh 多参数直拼会让远端 shell 把 # 注释/元字符吞掉，必须 shlex.join 成单条命令: {line.strip()}")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
