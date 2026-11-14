#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LINTS = ROOT / "lints"

DEV_ONLY_MARKERS = ("publish/", "README.public")


def lint() -> list[str]:
    problems = []
    for path in sorted(LINTS.glob("*.py")):
        if path.name == Path(__file__).name:
            continue
        text = path.read_text(encoding="utf-8")
        touches_dev_only = any(marker in text for marker in DEV_ONLY_MARKERS)
        if not touches_dev_only:
            continue
        gate = 'publish.sh").exists()'
        if gate not in text:
            problems.append(
                f"{path.name}: 触碰 dev-only 文件({', '.join(m for m in DEV_ONLY_MARKERS if m in text)})但无 publish.sh 存在性 no-op 闸——"
                "公开树被 publish.sh 出包时剥掉 publish/ 与 publish.sh 自身, lint 会在 CI 公开树把缺席当 finding 报红"
                "(c374a5e 极性反事故); 在 lint() 开头加: if not (ROOT / \"scripts\" / \"publish.sh\").exists(): return []"
            )
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
