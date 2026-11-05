#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

RESPAWN_BACKENDS = ("tmux", "direct")
INSTANCE_KEYS = ("session", "pane")


def lint() -> list[str]:
    problems = []
    from common import agents

    for cli in agents.cli_names():
        recipe = agents.respawn_recipe(cli)
        if recipe:
            backend = str(recipe.get("backend") or "")
            if backend not in RESPAWN_BACKENDS:
                problems.append(f"{cli}: respawn.backend={backend!r} 不在枚举 {RESPAWN_BACKENDS}——离线恢复无处方")
            if backend == "tmux" and not recipe.get("resume_args"):
                problems.append(f"{cli}: respawn backend=tmux 但缺 resume_args——respawn 后对话状态不复原")
        key = agents.multi_instance_key(cli)
        if key and key not in INSTANCE_KEYS:
            problems.append(f"{cli}: multi_instance.key={key!r} 不在枚举 {INSTANCE_KEYS}——分身无法追溯")
    if agents.multi_instance_key("claude") != "session":
        problems.append("claude: multi_instance.key 必须为 session——CC 以 CLAUDE_CODE_SESSION_ID 追溯分身(compact 换档不分裂)")
    if agents.multi_instance_key("pi") != "pane":
        problems.append("pi: multi_instance.key 必须为 pane——pi 无会话短码, 以 pane 锚追溯")
    claude_recipe = agents.respawn_recipe("claude")
    if claude_recipe.get("backend") != "tmux" or claude_recipe.get("resume_args") != ["-c"]:
        problems.append("claude: respawn 必须 tmux + resume_args=['-c']——主控通知下线节点时用启动命令恢复对话状态")
    if agents.respawn_recipe("pi").get("backend") != "direct":
        problems.append("pi: respawn 必须 backend=direct——pi 后台拉起即活, 不需要 tmux")
    if agents.respawn_recipe("codex"):
        problems.append("codex: 不应声明 respawn——主控定位, 外部进程无法替其恢复会话状态")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
