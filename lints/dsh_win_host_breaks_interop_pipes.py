#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "deploy" / "dsh" / "dsh-host-win.sh"
WSL_PORT = "3080"


def lint() -> list[str]:
    problems = []
    text = SCRIPT.read_text()
    spawn_line = next((line for line in text.splitlines() if "Start-Process" in line), "")
    if not spawn_line:
        problems.append(
            f"{SCRIPT.name}: 须以 powershell.exe Start-Process 起 win host——WSL interop 等待全部 "
            "Windows 后代 job, cmd.exe /c start /b 即使三层重定向断管也挂到 host 退出 "
            "(2026-11-12 活体: start /b 与 start /min 的长命子进程均令 WSL 侧 12s 不返, "
            "powershell Start-Process 立即返回)"
        )
        return problems
    if "start /b" in text or re.search(r"cmd\.exe /c \"start", text):
        problems.append(
            f"{SCRIPT.name}: 禁用 cmd.exe start /b 起 host——后代长命进程令 WSL 侧 interop 调用永久阻塞"
        )
    if '>/dev/null 2>&1 </dev/null' not in spawn_line:
        problems.append(f"{SCRIPT.name}: interop 调用须外层重定向 >/dev/null 2>&1 </dev/null 断 stdio 继承")
    if "< NUL" not in spawn_line or "2>&1" not in spawn_line:
        problems.append(f"{SCRIPT.name}: 内层 cmd 须 < NUL > <log> 2>&1, host stdio 落盘且确定 (token 抓取依赖)")
    if spawn_line.count('"') != 2 or spawn_line.count("'") != 2:
        problems.append(
            f"{SCRIPT.name}: spawn 行必须恰好一对 bash 双引号 + 一对 PS 单引号——再多一层引号经 "
            "interop/PS/cmd 多重解析即不可靠 (含空格路径由脚本头部 8.3 短路径校验拦截)"
        )
    port_default = re.search(r'win_port="\$\{WIN_PORT:-(\d+)\}"', text)
    if not port_default:
        problems.append(f"{SCRIPT.name}: win_port 默认值必须显式声明 (端口错开纪律)")
    elif port_default.group(1) == WSL_PORT:
        problems.append(
            f"{SCRIPT.name}: WIN_PORT 默认值不得为 {WSL_PORT}——mirrored 网络下 win/WSL 共享 "
            "127.0.0.1, 与 WSL 侧 host 同端口双监听冲突 (2026-11-12 实测纪律: WSL 3080 / win 3081)"
        )
    if "%%PATH%%" in spawn_line:
        problems.append(
            f"{SCRIPT.name}: 命令行语境 %%PATH%% 经双层 cmd 展开后留游离 % 污染 PATH 首尾条目"
            "(2026-11-12 活体: cmd /c \"cmd /c echo %%PATH%%\" 保留前导 %), 旧值拼接必须延迟展开"
        )
    if "/v:on" not in spawn_line or "!PATH!" not in spawn_line:
        problems.append(
            f"{SCRIPT.name}: set PATH 拼旧值必须目标 cmd 带 /v:on + !PATH! 延迟展开"
            "(/v:on 目标 cmd 执行期展开真值, 外层不展开)"
        )
    if 'occupied_pid="$(listen_pid)"' not in text:
        problems.append(
            f"{SCRIPT.name}: spawn 前必须端口占用预检——否则失败即杀的按端口 taskkill 可能误杀占端口的他人进程"
        )
    if 'orphan_pid="$(listen_pid)"' not in text or "taskkill /PID ${orphan_pid} /T /F" not in text:
        problems.append(
            f"{SCRIPT.name}: 60s 抓不到 token 的失败路径必须按端口解析 pid 并 taskkill 失败即杀——"
            "否则 win host 成孤儿继续监听, 下次重跑撞端口 (对齐 WSL 版 dsh-host.sh 的 kill 语义)"
        )
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
