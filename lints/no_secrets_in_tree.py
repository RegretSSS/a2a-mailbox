#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"ghp_[A-Za-z0-9]{30,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox[bp]-[A-Za-z0-9-]{20,}"),
    re.compile(r"zai[-_][A-Za-z0-9_-]{12,}"),
)
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules"}


def lint() -> list[str]:
    problems = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        for pattern in SECRET_PATTERNS:
            hit = pattern.search(text)
            if hit:
                problems.append(f"密钥扫描: {path.relative_to(ROOT)} 疑似凭据形态 {hit.group(0)[:12]}…——发布/提交前移除或改环境变量")
                break
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
