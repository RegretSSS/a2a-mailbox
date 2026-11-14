#!/usr/bin/env python3
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from common.version import __version__

SERVER = ROOT / "server.json"
MANIFEST = ROOT / "packaging" / "mcpb" / "manifest.json"
PYPROJECT = ROOT / "packaging" / "mcpb" / "pyproject.toml"
BUILD = ROOT / "scripts" / "build-mcpb.sh"


def lint() -> list[str]:
    problems = []
    for label, path in [("server.json", SERVER), ("packaging/mcpb/manifest.json", MANIFEST), ("packaging/mcpb/pyproject.toml", PYPROJECT), ("scripts/build-mcpb.sh", BUILD)]:
        if not path.exists():
            problems.append(f"{label} 缺失——MCPB 发布链材料不在 dev 树, 下次 publish 重产即回退")
    if problems:
        return problems
    try:
        server = json.loads(SERVER.read_text())
    except json.JSONDecodeError as exc:
        return [f"server.json 非法 JSON: {exc}"]
    try:
        manifest = json.loads(MANIFEST.read_text())
    except json.JSONDecodeError as exc:
        return [f"packaging/mcpb/manifest.json 非法 JSON: {exc}"]
    if server.get("name") != "io.github.RegretSSS/a2a-mailbox":
        problems.append(f"server.json name={server.get('name')!r} 不符——登记名漂移")
    packages = server.get("packages") or []
    if not packages or not packages[0].get("fileSha256"):
        problems.append("server.json packages[0] 缺 fileSha256——MCPB 资产指纹丢失")
    pyproject_match = re.search(r'^version\s*=\s*"([^"]+)"', PYPROJECT.read_text(), re.MULTILINE)
    pyproject_version = pyproject_match.group(1) if pyproject_match else None
    for label, version in [("server.json", server.get("version")), ("manifest.json", manifest.get("version")), ("pyproject.toml", pyproject_version)]:
        if version != __version__:
            problems.append(f"{label} version={version!r} 与 common/version.__version__={__version__!r} 不一致——升版漏改即错版发包")
    build_source = BUILD.read_text()
    if "packaging/mcpb" not in build_source:
        problems.append("build-mcpb.sh 不再引用 packaging/mcpb——打包脚本与模板脱钩")
    if "pack" not in build_source or 'rglob("*")' not in build_source or "tree" not in build_source:
        problems.append("build-mcpb.sh 解包区(tree)与打包根(pack)分离被破坏——tar 解包区整个卷进 zip 会把 .git 塞进 mcpb(实发 327 条目事故)")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
