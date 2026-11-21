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
            if backend == "direct" and not recipe.get("resume_args"):
                problems.append(f"{cli}: respawn backend=direct 但缺 resume_args——后台拉起的是全新失忆会话, 档原对话状态全丢(11-08 m02905 案: 手工构造 respawn 命令错层键入活 pi, 工具不安全逼人走险路)")
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
    if agents.respawn_recipe("pi").get("backend") != "direct" or agents.respawn_recipe("pi").get("resume_args") != ["-c"]:
        problems.append("pi: respawn 必须 direct + resume_args=['-c']——后台拉起即活且续原目录最近会话(pi -c), 裸 pi 是失忆重启")
    if agents.respawn_recipe("codex"):
        problems.append("codex: 不应声明 respawn——主控定位, 外部进程无法替其恢复会话状态")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
