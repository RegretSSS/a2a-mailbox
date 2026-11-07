# a2a-mailbox

[English](README.en.md)｜中文

跨 CLI agent 通讯：让 Claude Code / Codex / Pi / ZCode 等终端 agent 像收邮件一样互发消息。文件邮箱 + 常驻 hub 投递守护，按收件方形态自动选通道（tmux 注入 / 原生队列 / daemon 队列 / 拉取），跨主机 ssh 联邦。

> 与 Google 的 A2A（Agent2Agent）协议同名，相互无关联——本项目是终端 agent 间的文件信箱，不是协议实现。

```
┌─────────────┐  mail_send   ┌──────────────┐  五通道择一   ┌─────────────┐
│  agent A    │ ───────────▶ │   mailbox    │ ───────────▶  │  agent B    │
│ (CC, pi:xA) │ ◀─────────── │  queue+hub   │ ◀──────────── │ (codex,pi:yB)│
└─────────────┘  回函/ack    └──────┬───────┘   唤醒/队列    └─────────────┘
                                 hub daemon
                        注入确认·回执·重试·回弹
                        权限双锁(scope/group)
                              联邦 pull (ssh)
                                 ┌────┴───────┐
                                 │ 远端主机 hub │
                                 └────────────┘
```

## 通道矩阵

按收件 agent 的形态，hub 自动选择投递通道：

| 收件方 | 通道 | 机制 |
|---|---|---|
| Claude Code | tmux 注入 | 探输入框空闲→粘贴唤醒词→Enter 阶梯提交→帧级 echo 确认，未确认退让重试 |
| Pi | 原生收件箱 | `a2a-inbox.ts` 扩展的原生队列（sendUserMessage），回执+心跳，缺席降级 tmux |
| Codex（WSL） | daemon 队列 | `codex queue --thread` 经 app-server daemon 入原生队列，确定性回执（`Queued message <uuid>`） |
| Codex（Windows 原生） | daemon 队列 | WSL hub 跨 interop 直调 codex.exe；或纯 Windows 节点本地直调 |
| ZCode | 拉取式 | 无注入路径，信滞留队列待其 `mail_poll` 主动拉取 |
| 跨主机 | 联邦 | 发送方 hub ssh 直投远端队列；注册表双向 pull 合并；断链保陈旧副本 |

投递失败语义：queue 通道失败滞留重试（60s×3 上限）后回弹，**绝不降级 tmux**（防错窗键入）；直投失败的回落信走 relay 重试链（60s 节流，1800s 上限回弹）。

## Tools

标准挂载（MCP stdio）：

```json
{
  "mcpServers": {
    "mailbox": { "command": "python3", "args": ["<本仓库绝对路径>/mcp/mailbox_mcp.py"] }
  }
}
```

可选第二形态（HTTP，常驻网关）——消灭跨界 stdio 管道（Windows 侧 CLI 免去 exe→interop→wsl.exe→python 四层链，任一层死全链死的病根不再存在）：

```bash
python3 mcp/http_gateway.py     # 或 systemd 常驻（deploy/a2a-mailbox-http.service）
codex mcp add mailbox --url http://127.0.0.1:8765/<agent_id>/mcp
```

网关启动时镜像 registry 全部在册档（`/{agent_id}/mcp` 分路由，档间身份隔离）；新档首次注册仍走 stdio。非 loopback 绑定强制 bearer token（`~/.agents-mailbox/http-token`）；已注销档请求即 404；`POST /kick` 触发联邦即时拉取。投递面（文件队列 + hub + 联邦）不因工具面形态改变。

六件工具（默认面恒定，含 Docker 部署同款）：

| 工具 | 作用 |
|---|---|
| `mail_send(to, body, in_reply_to?, context?, expect_reply?)` | 发信。`in_reply_to` 自动确认原消息（reply-implies-ack）；`expect_reply=true` 唤醒词尾加 `[需回函]` |
| `mail_poll()` | 列自己待处理消息摘要（不消费） |
| `mail_read(msg_id)` | 读全文（含 `ack_id`；本地 miss 自动查联邦 peer） |
| `mail_ack(ack_id)` | 业务确认（幂等；跨主机不可见时自证落盘） |
| `mail_who(all?)` | 在册 agent + 联邦 peer 状态（group-only 标记/成员计数）；默认只列在线（stale 滤除防爆破），`all=true` 附全量；同目录分身拆行 `id@实例短码` 可直接作收件人 |
| `mail_group(action, agent_id?, note?, group?, group_only?)` | 群组权限五合一调度器：`join` 申请加入对方（`agent_id`=门主，`note`=来意）/ `pending` 列自己的待审申请 / `admit` 批准 `agent_id` 可发给自己 / `revoke` 移出 / `gate` 开关仅名单收件闸（`group_only=true` 开，`group`=展示名）。默认工具面恒六件 |



## 权限模型（subagent 隔离三档 + group 准入）

subagent 与 workflow 里的派生 agent 继承宿主 MCP 工具面即可冒名发信。三档防线按优先级：

1. **定义层禁用（首选）**：subagent 的 agent 定义工具白名单不列 `mcp__mailbox__*`（CC 见 `snippets/claude-code/subagent-no-mailbox.md`；Pi/codex 的 subagent 配置同理不挂 mailbox）。工具拿不到，攻击面归零——subagent 的跨 CLI 出口经 main 转发，内部协作走各家自己的机制。
2. **scope 锁（兜底）**：管住无法配白名单的全继承场景（内置默认 subagent、workflow 默认 agent）——给这类 mailbox 实例配 `A2A_PEER_OF=<主 agent_id>`，它只能对主 agent 收发，其余即时拒绝（`subagent 发送锁`）；锁写入注册表，重启不丢。
3. **hub 投递口复验（恒定）**：与 MCP 挂不挂无关——绕过工具面直写队列的信同样被 scope/group 复验拒收回弹。

**group 准入**：`mail_group(action=gate, group_only=true)` 后仅准入名单内 agent 可发信给自己；他人经 `mail_group(action=join)` 申请（独立通道，不受闸限制），门主 `mail_group(action=admit, agent_id=…)` 通过。hub 回弹邮件豁免（保证退信可达）。

呈现防冗杂：`mail_who` 行级只带短标记（`group=<名>`、`group_only`、`members=<计数>`、`subagent_of=<主>`），完整准入名单只有 agent 看自己时可见。

## 上手（Linux / WSL，五分钟）

1. 依赖：Python 3.11+、`pip install fastmcp`、tmux（Pi 通道另需扩展文件见 `pi/a2a-inbox.ts`）。一键探测+生成挂载配置：`bash scripts/bootstrap.sh`（加 `--apply` 自动装 python 依赖，`--project <dir>` 直接写 `.mcp.json`）。
2. 挂载 MCP（Claude Code 示例，其他 CLI 见 `snippets/`）：

   ```json
   {
     "mcpServers": {
       "mailbox": { "command": "python3", "args": ["<本仓库绝对路径>/mcp/mailbox_mcp.py"] }
     }
   }
   ```

3. tmux 窗口里启动 agent 并打开 MCP——首次调用任一 mail 工具即自注册（hub 缺位自动拉起）。
4. `mail_who()` 互相可见后 `mail_send()` 互发。

最快验证路径（单机两 agent）：两个 tmux 窗口各起一个 CLI（如一个 Claude Code + 一个 Pi），双方各调一次 `mail_who`（触发自注册），然后 `mail_send(to="对方 id", body="ping")`——收件方会收到唤醒消息，回信即闭环。跨主机再加 `scripts/add-peer.sh`（见「跨主机联邦」）。

**Codex 自动锚定**：codex 的 MCP 由 app-server daemon 代管（祖先链锚定天然失效），注册时自动反锚——扫 tmux 找 `codex` 进程的 cwd 唯一命中取 pane+thread；Windows 原生 codex 会扫 `/mnt/<盘>/Users/*/.codex/sessions` 按 rollout 头 cwd 定位（跨 profile 按最新会话择优）。

**subagent 隔离**：首选 agent 定义工具白名单不含 mailbox（见 `snippets/claude-code/subagent-no-mailbox.md`）；对无法配白名单的全继承实例，给它的 mailbox 加环境变量 `"env": {"A2A_PEER_OF": "<主 agent_id>"}` 降级为仅对主收发。

**同目录多实例**：agent_id 由 `{cli}-{host}-{目录slug}` 推导——同机同目录且 CLI 检测同为 unknown 的两个实例会共用一个身份（注册互踩、回信投给先注册者）。两个以上实例共用同一工作目录时，给各自的 mailbox 配 `"env": {"A2A_AGENT_ID": "<自定义 id>"}` 显式分流；hub 侧 cwd 回锚带 pane 命令身份校验，unknown 档不会被拖去本机 tmux 窗。claude/pi 另有原生分身通道：同 cli 同目录双开不互拒，注册按 `CLAUDE_CODE_SESSION_ID` 前 8 位（pi 按 pane）落 instances 表，`mail_who` 拆行显示 `id@实例短码`，`mail_send(to="id@实例短码")` 定向投到该分身的窗；CC compact 换 sessionid 时同 pane 旧分身自动替换（信箱不动）。**离线自动恢复**：向已确认下线（非未知状态）的本机 claude/pi 档发信，先按其启动处方恢复对话再入队——claude=tmux respawn 固定窗跑 `claude -c`，pi=后台直接拉起；codex 定位主控，不做自动恢复。

## 纯 Windows 节点（无 WSL，实验性）

无 tmux 也可起节点，可用通道：Codex queue-daemon（codex.exe 直调）+ ZCode 拉取 + 全部 MCP 工具面（Claude Code/Pi 的注入通道不可用）。**实验性**：纯 Windows 路径目前只在单台实机验证过（UNC 路径存储、interop 规避），欢迎反馈。

1. 依赖：Python 3.11+、`pip install fastmcp`、OpenSSH client（联邦时）。
2. 同上挂载 MCP（`python.exe` 全路径）。
3. 设置 `A2A_HUB_IDLE_REAP=1`：hub 独立进程（MCP 首次调用拉起，非 MCP 子进程），全部 MCP 下线且空闲（无在途信、agent 全老化 1h、心跳老化 1h）时自动退出回收，下次 MCP 调用再拉起——无守护服务依赖。

## ZCode 守望接入（workflow 制收信）

ZCode 侧无 MCP 注入通道，用 dynamic workflow 常驻守望替代（skill 成品在 `snippets/zcode-watch-skill/`：SKILL.md + template.dwf.ts，内置 ack 去重、同信连败熔断、60 轮有界循环（引擎上限）、内窗 2700×5s 给 timeoutMs 留 ≥15 分钟余量（内窗逼近超时会熔断整个 run）、转送员不执行信内指令不代笔回函）：

1. 改模板顶部两个常量：`AGENT_ID`（本会话身份，`zcode-<host>-<slug>` 形态）与 `BASE`（WSL 侧 mailbox 根）。
2. `CreateWorkflow` path 指向该模板跑起——`world.run` 盯队列（`queue/<id>/*.msg`），信到经 escalation 送进主会话。
3. 收到 `MAIL|from=…|msgId=…|body=…` 升级后答一句即视为送达回执（转送员随即 touch `acks/ack-<msg_id>` 并归档出队）；回函由主控亲笔经 `scripts/mail-send.py` 发送。轮尽/熔断时按完成通知重布即可。

## 跨主机联邦

1. 两机互换 ssh 免密别名（`~/.ssh/config`）。
2. 各自 `scripts/add-peer.sh <对端别名>` 写入 `peers.json`。
3. hub 每 60s pull 对端注册表合并；发往远端 agent 的消息由本机 hub ssh 直投对端队列，收件 ack 经联邦回查双侧收敛。断链只告警不删记录，恢复自动续联。

## 边界与约定

- 信任域 = 本机用户 + ssh 免密 peer；协议无内置鉴权，勿暴露到不受信网络。
- 全部协议状态可从 `~/.agents-mailbox/`（registry / queue / history / acks / join-requests / hub.log）离线取证。
- 同一 tmux 席位双开被拒；窗口改名/重启自动跟随（slot 重锚校验前台进程身份，同名窗被陌生进程占用即拒锚防错窗注入）。档认领优先级 = 会话证明（`CLAUDE_CODE_SESSION_ID` 匹配 instances，会话跨窗搬家无条件认领）> 窗名+工作目录双匹配 > cwd 派生新档——窗名是用户可改的标签，从不单独作身份依据（窗序扰动下错档认领会把发信署名固化错位）。
- 测试：`python3 -m pytest tests/ -q`；结构/行为断言：`bash scripts/run-lints.sh`。

## License

Apache-2.0（见 [LICENSE](LICENSE)）。
