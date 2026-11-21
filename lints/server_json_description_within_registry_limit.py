#!/usr/bin/env python3
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER_JSON = ROOT / "server.json"
REGISTRY_DESCRIPTION_LIMIT = 100


def lint() -> list[str]:
    problems = []
    if not SERVER_JSON.exists():
        problems.append("server.json: 缺失——mcp registry 发布面不存在")
        return problems
    payload = json.loads(SERVER_JSON.read_text(encoding="utf-8"))
    description = str(payload.get("description") or "")
    if len(description) > REGISTRY_DESCRIPTION_LIMIT:
        problems.append(
            f"server.json: description {len(description)} 字符超 registry 上限 {REGISTRY_DESCRIPTION_LIMIT}"
            "——mcp-publisher publish 会 422 打回(a950ad8 实案); 缩句保留五通道+联邦语义"
        )
    packages = payload.get("packages") or []
    for index, package in enumerate(packages):
        identifier = str(package.get("identifier") or "")
        if identifier and "__VERSION__" in identifier:
            problems.append(f"server.json: packages[{index}].identifier 含未替换占位符")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
