#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "plugins" / "gateway-mailbox" / "mailbox.hooks.mjs"

QUEUE_MUTATORS = ("unlinkSync", "renameSync(queue", "rmSync", "appendFileSync(path.join(root, \"queue", "writeFileSync(path.join(root, \"queue")


def lint() -> list[str]:
    problems = []
    source = HOOK.read_text(encoding="utf-8")
    for mutator in QUEUE_MUTATORS:
        if mutator in source:
            problems.append(f"plugins/gateway-mailbox/mailbox.hooks.mjs: 禁止出现 {mutator}——magpie hook 只读队列(通知语义), 消费/归档/移动信件会把『通知』变『投递』, 托管验证失效时信成孤儿")
    if "readdirSync" not in source:
        problems.append("plugins/gateway-mailbox/mailbox.hooks.mjs: 队列检查必须 readdirSync 只读——hook 无任何写队列的合法路径")
    if "return undefined" not in source.split("export async function onRequest", 1)[-1]:
        problems.append("plugins/gateway-mailbox/mailbox.hooks.mjs: onRequest 全路径必须可静默放行(兜底 return undefined)——hook 失败不得伤 magpie 主链")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
