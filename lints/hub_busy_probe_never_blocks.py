#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMUXIO = ROOT / "common" / "tmuxio.py"
HUB = ROOT / "hub" / "hub.py"


def lint() -> list[str]:
    problems = []
    tmux_src = TMUXIO.read_text()
    if "def pane_busy" in tmux_src or "BUSY_PROBE_SPAN_SECONDS" in tmux_src:
        problems.append(
            "common/tmuxio.py: 禁止 sleep 版 pane_busy——K 封并发投递每秒被占 0.6K 秒, "
            "必须拆 busy_probe_frame/frame_grew_since 两原语由 hub 跨 tick 采样"
        )
    if "def busy_probe_frame" not in tmux_src or "def frame_grew_since" not in tmux_src:
        problems.append("common/tmuxio.py: busy 探测必须提供 busy_probe_frame/frame_grew_since 两原语")
    if tmux_src.split("def frame_grew_since", 1)[-1].split("def ", 1)[0].find("sleep") >= 0:
        problems.append("common/tmuxio.py: frame_grew_since 内不得出现 sleep")

    hub_src = HUB.read_text()
    occupied = hub_src.split("def pane_occupied", 1)[-1].split("def ", 1)[0]
    if "sleep" in occupied:
        problems.append("hub/hub.py: pane_occupied 内不得出现 sleep——投递主循环阻塞会饿死其余在途信")
    if "busy_probe_at" not in occupied or "frame_grew_since" not in occupied:
        problems.append("hub/hub.py: pane_occupied 必须两相采样(首 tick 存 frame 退让, 次 tick 比对增长)")
    slots = hub_src.split("class Delivery", 1)[-1].split("__slots__", 1)[-1].split(")", 1)[0]
    if "busy_probe_at" not in slots or "busy_probe_frame" not in slots:
        problems.append("hub/hub.py: Delivery 必须挂 busy_probe_at/busy_probe_frame slot")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
