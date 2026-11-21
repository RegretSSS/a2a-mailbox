#!/usr/bin/env bash
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
ROOT="${A2A_MAILBOX_ROOT:-$HOME/.agents-mailbox}"
MODE="check"
PROJECT_DIR=""

usage() {
  cat <<'USAGE'
用法: scripts/bootstrap.sh [--apply] [--project <dir>]
  默认 check 模式: 探测环境并打印各 CLI 挂载配置, 不写任何文件
  --apply         自动装缺失的 python 依赖(pip install fastmcp)
  --project <dir> 把 Claude Code 挂载写入 <dir>/.mcp.json(已存在则跳过并打印手动段)
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --apply) MODE="apply" ;;
    --project) shift; PROJECT_DIR="${1:-}" ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
  shift
done

status=0

python_ok() {
  command -v python3 >/dev/null 2>&1 || return 1
  python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null
}

if python_ok; then
  echo "python3 $(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])') ok"
else
  echo "python3 >= 3.11 缺失——先装 python3.11+ 再来" >&2
  exit 1
fi

if python3 -c 'import fastmcp' 2>/dev/null; then
  echo "fastmcp $(python3 -c 'import importlib.metadata as m; print(m.version("fastmcp"))') ok"
else
  if [ "$MODE" = "apply" ]; then
    python3 -m pip install 'fastmcp>=4,<5'
    echo "fastmcp 已装"
  else
    echo "fastmcp 缺失——重跑加 --apply 自动装, 或手动 pip install 'fastmcp>=4,<5'"
    status=1
  fi
fi

if command -v tmux >/dev/null 2>&1; then
  echo "tmux $(tmux -V | cut -d' ' -f2) ok"
else
  echo "tmux 缺失——注入通道需要它; 纯拉取模式可无 tmux 继续" >&2
fi

mkdir -p "$ROOT"
echo "mailbox root: $ROOT"

MCP_BLOCK=$(cat <<JSON
{
  "mcpServers": {
    "mailbox": { "command": "python3", "args": ["${REPO}/mcp/mailbox_mcp.py"] }
  }
}
JSON
)

echo
echo "== Claude Code 挂载(写入项目 .mcp.json) =="
if [ -n "$PROJECT_DIR" ]; then
  TARGET="$PROJECT_DIR/.mcp.json"
  if [ -f "$TARGET" ]; then
    echo "$TARGET 已存在, 手动并入以下段落:"
    echo "$MCP_BLOCK"
  else
    mkdir -p "$PROJECT_DIR"
    printf '%s\n' "$MCP_BLOCK" > "$TARGET"
    echo "已写入 $TARGET"
  fi
else
  echo "$MCP_BLOCK"
fi

echo
echo "== Pi 挂载 =="
echo "mcp.json 段落同上(${REPO}/mcp/mailbox_mcp.py); 扩展文件:"
echo "  mkdir -p ~/.pi/agent/extensions && cp ${REPO}/pi/a2a-inbox.ts ~/.pi/agent/extensions/"

echo
echo "== Codex (WSL) =="
echo "把 ${REPO}/snippets/codex/config.mailbox.toml 追加进 ~/.codex/config.toml"

echo
echo "== ZCode =="
echo "守望 skill 见 ${REPO}/snippets/zcode-watch-skill/(SKILL.md 两个常量改完即用)"

echo
echo "== 五分钟验证 =="
cat <<'VERIFY'
1. 两个 tmux 窗口各起一个 CLI(如一个 Claude Code + 一个 Pi), 打开各自的 mailbox MCP
2. 双方各调一次 mail_who(触发自注册, hub 缺位自动拉起)
3. mail_send(to="对方 id", body="ping") —— 收件方收到唤醒消息, 回信即闭环
4. 跨主机: 对端互换 ssh 免密别名后 scripts/add-peer.sh <对端别名>
VERIFY

if [ "$status" -ne 0 ]; then
  echo
  echo "check 模式发现问题(见上), --apply 可自动修复 python 依赖" >&2
  exit 1
fi
