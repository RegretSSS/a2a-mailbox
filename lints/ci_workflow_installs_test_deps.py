#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CI = ROOT / ".github" / "workflows" / "ci.yml"


def lint() -> list[str]:
    problems = []
    if not CI.exists():
        return ["ci.yml 缺失——GH Actions 门面丢失, 公开仓无测试门禁"]
    source = CI.read_text()
    install_lines = [line for line in source.splitlines() if "pip install" in line]
    if not install_lines:
        problems.append("ci.yml 无 pip install——runner 裸环境, pytest/fastmcp 全缺即挂")
    joined = " ".join(install_lines)
    if not re.search(r"\bpytest\b", joined):
        problems.append("ci.yml 装依赖漏 pytest——runner 不预装, tests 步骤必挂(GH 首跑实发 ad7f414 前形态)")
    if not re.search(r"fastmcp[><=~]", joined):
        problems.append("ci.yml 的 fastmcp 未锁版本界——大版本漂移会静默改变 MCP 行为")
    if "run-lints.sh" not in source:
        problems.append("ci.yml 缺 run-lints.sh 步骤——lint 门禁不在 CI 里")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
