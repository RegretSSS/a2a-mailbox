#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "deploy" / "dsh" / "dsh-host-win-native.ps1"
PARAM_DEFAULT_BACKSTOP = '$MagpieKey = "magpie"'
ENV_FIRST_FALLBACK = (
    'if (-not $MagpieKey) { $MagpieKey = if ($env:MAGPIE_GATEWAY_KEY) '
    '{ $env:MAGPIE_GATEWAY_KEY } else { "magpie" } }'
)


def lint() -> list[str]:
    problems = []
    text = SCRIPT.read_text()
    if PARAM_DEFAULT_BACKSTOP in text:
        problems.append(
            f"{SCRIPT.name}: -MagpieKey 参数默认焊死 \"magpie\" + 无条件 $env:MAGPIE_GATEWAY_KEY 赋值"
            "会静默覆盖调用环境已设的 gateway key——host 起得来但 LLM 调用全部认证失败"
        )
    if ENV_FIRST_FALLBACK not in text:
        problems.append(
            f"{SCRIPT.name}: 赋值前必须 env 优先回退 (if (-not $MagpieKey) 先取 $env:MAGPIE_GATEWAY_KEY "
            "再兜底 magpie)——对齐 dsh-host.sh/dsh-host-win.sh 的 ${{MAGPIE_GATEWAY_KEY:-magpie}} 契约"
        )
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
