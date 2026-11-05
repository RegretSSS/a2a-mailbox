#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SPEC_RE = re.compile(r"^SPEC\s*=\s*\{", re.M)
CLI_RE = re.compile(r'"cli":\s*"([a-z0-9-]+)"')
KIND_RE = re.compile(r'"delivery_kind":\s*"([a-z-]+)"')


def lint() -> list[str]:
    problems = []
    sys.path.insert(0, str(ROOT))
    from common import agents

    seen: set[str] = set()
    for path in sorted((ROOT / "common" / "agents").glob("*.py")):
        if path.name == "__init__.py":
            continue
        source = path.read_text()
        if not SPEC_RE.search(source):
            problems.append(f"{path.name}: 缺 SPEC 声明——AgentAPP 包内每个文件必须是一条 cli spec")
            continue
        cli = CLI_RE.search(source)
        kind = KIND_RE.search(source)
        if not cli or not kind:
            problems.append(f"{path.name}: SPEC 缺 cli 或 delivery_kind 键")
            continue
        if kind.group(1) not in agents.DELIVERY_KINDS:
            problems.append(f"{path.name}: delivery_kind={kind.group(1)!r} 不在枚举 {agents.DELIVERY_KINDS}")
        if cli.group(1) in seen:
            problems.append(f"{path.name}: cli={cli.group(1)!r} 重复声明")
        seen.add(cli.group(1))
    spec_files = set(seen)
    registered = set(agents.cli_names())
    if spec_files != registered:
        missing = spec_files - registered
        stale = registered - spec_files
        if missing:
            problems.append(f"注册表漏聚合: {sorted(missing)} 有 spec 文件但未进 agents.cli_names()——自动发现失效")
        if stale:
            problems.append(f"注册表藏私货: {sorted(stale)} 在聚合里但无对应 spec 文件")
    for cli in agents.pull_only_clis():
        if agents.delivery_kind(cli) != "pull-only":
            problems.append(f"{cli}: pull_only_clis 与 delivery_kind 不一致")
    tmux_default = agents.delivery_kind("never-registered-cli")
    if tmux_default != "tmux":
        problems.append(f"未注册 cli 的默认 kind 应为 tmux 兜底, 实得 {tmux_default!r}")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
