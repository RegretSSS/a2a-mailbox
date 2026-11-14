#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "deploy" / "dsh" / "dsh-host-win-native.ps1"


def lint() -> list[str]:
    problems = []
    text = SCRIPT.read_text()
    if "wsl.exe" in text:
        problems.append(f"{SCRIPT.name}: 纯 win 托管 host 零 wsl.exe——node 由 win 本地解析启动")
    if "-PassThru" not in text:
        problems.append(
            f"{SCRIPT.name}: Start-Process 必须 -PassThru 拿精确 pid——事后按端口反查 pid 可能撞上同端口的他人进程"
        )
    if "taskkill.exe /PID $proc.Id /T /F" not in text:
        problems.append(
            f"{SCRIPT.name}: 60s 抓不到 token 的失败路径必须按精确 pid taskkill /T /F——"
            "host 成孤儿继续监听, 下次重跑撞端口 (对齐 WSL 版失败即杀语义)"
        )
    if "Get-NetTCPConnection -LocalPort $WinPort -State Listen" not in text:
        problems.append(f"{SCRIPT.name}: spawn 前必须端口占用预检——失败即杀的按端口定位需要先证明端口无人")
    if "dsh-hosts" not in text:
        problems.append(f"{SCRIPT.name}: token 必须落入 mailbox root 的 dsh-hosts/ (ensure_cookie 按 <agent_id>.token 读取)")
    if "Remove-Item $cookiePath" not in text:
        problems.append(
            f"{SCRIPT.name}: 写 token 未清旧 cookie——host 重启=新 launch token, "
            "ensure_cookie 对未过期旧 cookie 直接复用, 失配 cookie 最长 27 天投递 401"
        )
    if "icacls.exe $tokenPath /inheritance:r" not in text:
        problems.append(f"{SCRIPT.name}: token 落盘后必须 icacls 断继承仅留本人——drvfs chmod 对 NTFS 是空操作, 0600 语义靠 ACL")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    sys.exit(1 if found else 0)
