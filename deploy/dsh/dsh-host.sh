#!/usr/bin/env bash
set -euo pipefail

agent_id="${A2A_AGENT_ID:-dsh-${A2A_HOST_TAG:-$(hostname -s)}}"
mailbox_root="${A2A_MAILBOX_ROOT:-$HOME/.agents-mailbox}"
dsh_root="${DSH_ROOT:-$HOME/workspace/deepseek-harness}"
magpie_key="${MAGPIE_GATEWAY_KEY:-magpie}"
node_bin="${NODE_BIN:-$HOME/tools/node-v24.22.2-linux-x64/bin}"

log_file="${DSH_HOST_LOG:-/tmp/dsh-host-${agent_id}.log}"
token_dir="$mailbox_root/dsh-hosts"
mkdir -p "$token_dir"

cd "$dsh_root"
env -i \
  HOME="$HOME" PATH="$node_bin:$PATH" DSH_HOME="${DSH_HOME:-$HOME/.dsh}" \
  MAGPIE_GATEWAY_KEY="$magpie_key" \
  pnpm dsh web --no-open >"$log_file" 2>&1 &
host_pid=$!

token=""
for _ in $(seq 1 60); do
  token=$(grep -oE 'token=[A-Za-z0-9_-]+' "$log_file" | head -1 | cut -d= -f2 || true)
  if [ -n "$token" ]; then
    break
  fi
  if ! kill -0 "$host_pid" 2>/dev/null; then
    echo "dsh host 启动即退, 见 $log_file" >&2
    exit 1
  fi
  sleep 1
done
if [ -z "$token" ]; then
  echo "60s 内未捕获 launch token, 见 $log_file" >&2
  kill "$host_pid" 2>/dev/null || true
  exit 1
fi

umask 077
printf '%s' "$token" > "$token_dir/$agent_id.token"
rm -f "$token_dir/$agent_id.cookie"
echo "dsh host pid=$host_pid agent_id=$agent_id token -> $token_dir/$agent_id.token"
wait "$host_pid"
