#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

STALE_TERMS = (
    "WAIT_ECHO",
    "BACKOFF",
    "退让重试",
    "退避重注",
    "falls back to tmux",
    "backoff retries",
    "frame-level echo",
    "帧级 echo",
)
STALE_PATTERNS = (r"(?<!绝不)降级 tmux",)


def lint() -> list[str]:
    if not (ROOT / "scripts" / "publish.sh").exists():
        return []
    problems = []
    for name in ("publish/README.public.md", "publish/README.en.public.md"):
        target = ROOT / name
        if not target.exists():
            problems.append(f"{name}: public 模板缺失——publish.sh 依赖它产出公开 README")
            continue
        text = target.read_text(encoding="utf-8")
        checks = [(term, re.escape(term)) for term in STALE_TERMS] + [
            (pattern, pattern) for pattern in STALE_PATTERNS
        ]
        for label, pattern in checks:
            for matched in re.findall(rf".{{0,30}}{pattern}.{{0,30}}", text):
                problems.append(
                    f"{name}: 残留旧投递语义「{label}」——…{matched}…；"
                    "主 README 语义变更后 public 模板没跟（v18 首 tar 被终检拦下的同族分叉）"
                )
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
