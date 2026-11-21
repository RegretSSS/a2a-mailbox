#!/usr/bin/env bash
set -euo pipefail

agent_id="${A2A_AGENT_ID:-dsh-${A2A_HOST_TAG:-host-a}-win}"
mailbox_root="${A2A_MAILBOX_ROOT:-$HOME/.agents-mailbox}"
win_port="${WIN_PORT:-3081}"
magpie_key="${MAGPIE_GATEWAY_KEY:-magpie}"
magpie_key_ps="${magpie_key//\"/\`\"}"
node_win_bin="${NODE_WIN_BIN:-C:\\nvm4w\\nodejs}"
: "${DSH_WIN_ROOT:?需设 win 侧 dsh 构建场 Windows 路径, 形如 D:\\dsh}"
: "${WIN_USER:?需设 Windows 用户名}"

for win_path_var in DSH_WIN_ROOT NODE_WIN_BIN WIN_USER; do
  if [[ "${!win_path_var:-}" == *" "* ]]; then
    echo "${win_path_var} 含空格——cmd /c 单参串内嵌引号经 interop 后不可靠, 改用 8.3 短路径 (win 侧 dir /x 可查): ${!win_path_var}" >&2
    exit 1
  fi
done

win_temp='C:\Users\'"${WIN_USER}"'\AppData\Local\Temp'
log_win="${win_temp}\\dsh-host-${agent_id}.log"
log_wsl="/mnt/c/Users/${WIN_USER}/AppData/Local/Temp/dsh-host-${agent_id}.log"

token_dir="$mailbox_root/dsh-hosts"
mkdir -p "$token_dir"

cd /mnt/c

listen_pid() {
  cmd.exe /c "netstat -ano -p tcp | findstr :${win_port} | findstr LISTENING" 2>/dev/null | tr -d '\r' | awk '{print $NF}' | head -1 || true
}

occupied_pid="$(listen_pid)"
if [ -n "$occupied_pid" ]; then
  echo "端口 ${win_port} 已被 pid=${occupied_pid} 占用, 先停它: cmd.exe /c \"taskkill /PID ${occupied_pid} /T /F\"" >&2
  exit 1
fi

rm -f "$log_wsl"

powershell.exe -NoProfile -Command "Start-Process -WindowStyle Hidden cmd -ArgumentList '/v:on /c cd /d ${DSH_WIN_ROOT} && set PATH=${node_win_bin};!PATH! && set MAGPIE_GATEWAY_KEY=${magpie_key_ps} && node apps\\cli\\lib\\bin.js web --no-open --port ${win_port} < NUL > ${log_win} 2>&1'" >/dev/null 2>&1 </dev/null

token=""
for _ in $(seq 1 60); do
  token=$(grep -aoE 'token=[A-Za-z0-9_-]+' "$log_wsl" 2>/dev/null | head -1 | cut -d= -f2 || true)
  if [ -n "$token" ]; then
    break
  fi
  sleep 1
done
if [ -z "$token" ]; then
  echo "60s 内未捕获 launch token, 见 $log_wsl" >&2
  orphan_pid="$(listen_pid)"
  if [ -n "$orphan_pid" ]; then
    cmd.exe /c "taskkill /PID ${orphan_pid} /T /F" >/dev/null 2>&1 || true
    echo "已按失败即杀清理占用 ${win_port} 的 host 进程 pid=${orphan_pid}" >&2
  fi
  exit 1
fi

umask 077
printf '%s' "$token" > "$token_dir/$agent_id.token"
rm -f "$token_dir/$agent_id.cookie"

win_pid="$(listen_pid)"
echo "dsh win host agent_id=$agent_id port=${win_port} pid=${win_pid:-未知} token -> $token_dir/$agent_id.token"
echo "停止: cmd.exe /c \"taskkill /PID ${win_pid} /T /F\" (精确 pid, 勿宽匹配)"
