# 挂载 snippets（待用，不自动并入任何现有配置）

| 端 | 文件 | 状态 |
|---|---|---|
| Claude Code | `claude-code/mcp.json` | 本仓 `.mcp.json` 同款（`${CLAUDE_PROJECT_DIR:-.}` 展开版），其他项目按此复制为该项目 `.mcp.json` |
| codex (WSL) | `codex/config.mailbox.toml` | 追加进 `~/.codex/config.toml` 的代码块，未挂载实测 |
| codex (win) | `codex/config.mailbox.win.toml` | **已实测**：wsl.exe 桥进 Linux python（存储/tmux 同根），pane 锚点用 `A2A_PANE_ID`/`A2A_CLI` 显式 env，respawn 保 pane 号、重建窗口需改 |
| pi | `pi/mcp.json` | 本机未装 pi（`~/.pi/agent` 仅有模型配置），装好后按其 MCP 挂载文档落位；JSON 为通用 mcpServers 格式 |

部署时 AI 一行替换：
- `<REPO_PATH>`（codex TOML×2 与 pi mcp.json）→ 本仓绝对路径（如 `/home/user-a/workspace/a2a-mailbox`）——这些端没有变量展开机制
- Claude Code 端不需要替换：`${CLAUDE_PROJECT_DIR:-.}` 自动指向项目根（`:-` 默认值必带，裸变量不展开且报缺变量警告）

统一要素：
- command 固定 `python3`（WSL 侧），脚本路径见上
- 存储根默认 `~/.agents-mailbox`，可用环境变量 `A2A_MAILBOX_ROOT` 覆盖（win 侧必须覆盖为 UNC 路径指向同一份 WSL 存储）
- 主机身份不再需要 `A2A_HOST_TAG` env：`~/.agents-mailbox/host_tag` 缓存优先（tailscale 名落缓存），detect 按 env→缓存→tailscale→hostname 四级解析
- win 侧 spawn 投递：注册时经 `A2A_SPAWN_CMD` 声明一次性命令（hub 在 WSL 侧执行），形态参照 `scripts/win-codex.sh` 包装 `codex exec`，联调时再定稿
- 入联邦：`scripts/add-peer.sh <对方ssh别名>` 一条命令（免密探测+ssh-copy-id 兜底+双端 peers.json+拉取验证）
