# dsh (DeepSeek Harness) 适配包

rpc-inbox 投递通道: hub 经 dsh web host 的 `/api` RPC 把信投进会话原生收件箱
(`session/prompt`, running 会话 steer 打断 / idle 会话 queue 唤醒), 零模型配合、零 tmux 依赖。

## 部署步骤 (WSL 侧)

1. **构建场上游 dsh** (参照 memory/dsh-build-recipe): `pnpm install && pnpm run build`, Node ≥24.9。

2. **安装 cordis.patch.yml**: 把本目录模板合并进 `~/.dsh/profiles/web/cordis.patch.yml`
   (顶层 `- insert:` 包裹, `name` 必须是**绝对路径指到** `packages/mcp/mcp-client/lib/index.js`,
   指目录=ERR_UNSUPPORTED_DIR_IMPORT, 裸包名=bundle 依赖图外解析失败)。

3. **写 launch token**: `bash deploy/dsh/dsh-host.sh` 启动 host, 它从启动日志抓
   `?token=...` 写到 `~/.agents-mailbox/dsh-hosts/<agent_id>.token` (0600)。
   host 常驻; token 随 cookie 换取 (30 天有效)。

4. **身份与透传** (cordis.patch.yml 的 `config.env`, 缺一不可):
   - `A2A_AGENT_ID`: 档名 (显式身份, 短路一切 cwd/claims 认领)
   - `A2A_CLI: dsh`: SPEC 路由 (常驻 host 无 pane, 进程名探测不可达)
   - `A2A_PANELESS: '1'`: 无 pane 语义, 档位不携带 tmux 元数据
   - `A2A_RPC_INBOX_URL`: hub 投递端点

5. **验证**: 会话里调 `mail_who` → 名单出现 `<agent_id>`; CC 侧 `mail_send` 往该档发信 →
   hub 日志 `via=dsh-rpc`, 信注入会话收件箱。

## 心跳语义

档位活性 = MCP 进程存活 (注册后每 300s 后台线程 re-register 刷 `last_seen`, 600s 活性窗), 与模型调工具频率解耦。
host 停则进程亡, 档位 1800s 后 prune 归档。

## Windows 侧

win 侧 stdio 挂载两形态, **纯 win 为主形态** (2026-11-12 晚活体定谳), wsl.exe 桥降级为
「mailbox 根必须留在 WSL 的主机机器」变体。rpc-inbox 档必须走 stdio——http gateway
只镜像在册档且无心跳面, paneless rpc 档 600s stale、1800s prune 后信回弹无自愈。

### 纯 win 主形态 (python.exe + UNC 代码加载 + win 原生根)

- **MCP**: win python.exe 直跑仓内脚本, 代码经 UNC 只读加载
  (`\\wsl.localhost\<wsl-distro>\...\a2a-mailbox\mcp\mailbox_mcp.py`), 全部写路径落
  win 原生 NTFS 根 `C:\Users\<user>\.agents-mailbox`——零 9P 写、零 wsl.exe。
  insert 模板: `cordis.patch.purewin.yml` (占位符: `<dsh-win-root>`/`<win-python-exe>`/
  `<repo-unc>`/`<win-session-dir>`/`<host-tag>`/`<win-port>`/`<win-mailbox-root>`)。
- **hub**: MCP 首调自动拉起 (hub_boot 用 sys.executable + DETACHED_PROCESS), env
  `A2A_HUB_IDLE_REAP=1` 空闲自回收; 注册锁/hub.lock 走 msvcrt 双平台分支。
- **win 侧最小部署拷贝是退路不是主路径**: UNC 代码加载活体已过 (MCP 注册+hub 拉起+
  rpc 投递全链), 主路径零同步成本; UNC 不可用时再拷 `mcp/+common/+hub/` 到
  `C:\Users\<user>\a2a-mailbox\` 并把 `<repo-unc>` 换成本地路径。

#### 部署步骤 (纯 win)

1. **前置**: win 装 Store python + `pip install fastmcp`; `wsl.exe -l` 查**发行版共享名**
   (UNC 用它, 本机是 `Ubuntu` 而非 `Ubuntu-22.04`——写错盘符名不报 not-found,
   而是 python `Errno 22 Invalid argument` / cmd「用户名或密码不正确」的双假象, 排查半天)。
2. **cordis.patch.yml 加 insert**: 用 `cordis.patch.purewin.yml` 模板替换占位符;
   `cwd` 决定哪些会话能收信 (会话 cwd == 记录 cwd 才被 pick, win 形路径即可,
   `cwd_matches` 会规范化比对)。
3. **写 launch token 到 win 根**: 托管 host 起即抓——`powershell -File deploy/dsh/dsh-host-win-native.ps1`
   (在 dsh 构建场目录里跑, 免传路径参数; `-AgentId` 与 insert 档名一致)。token 落
   `<win-mailbox-root>\dsh-hosts\<agent_id>.token`, icacls 断继承仅留本人 (drvfs chmod
   对 NTFS 是空操作, 0600 语义靠 ACL)。
4. **端口错开**: mirrored 网络下 win↔WSL 共享 127.0.0.1, WSL 侧 host 默认 3080, win 侧 3081。
5. **验证**: 会话里调 `mail_who` → 名单出现 `<agent_id>`; 跨端 `mail_send` 往该档发信 →
   win 根 hub.log `injected ... via=dsh-rpc` (mode=steer/queue 如实记录)。

#### 纯 win 实测边界 (2026-11-12 活体)

- **全链闭环物证**: win python MCP 注册进 win 根 (cli=dsh+rpc_inbox_url+win 形 cwd) →
  MCP 首调拉起 DETACHED python.exe hub → 探针 `mail_send` 后 14s hub.log
  `injected af211a999d27 round=1 via=dsh-rpc (session=... mode=queue)`, session/list 的
  `updatedAt` 同秒被 session/prompt 撞动——入队即送达坐实。
- **hub 轮询降级扫描修复**: nt 无 inotify, hub 降级 2s 轮询; 原实现 `slow_due` 在
  sleep 前取样、`scan_scope` 拿陈旧值, 轮询节点全量扫描只在首轮出现一次, 队内信封
  无人扫 (活体: rpc-inbox 信滞留 126s 零投递)。修=sleep 后重算 `slow_due`;
  behavioral lint `polling_mode_scan_always_full` 重放原始失败。
- **WSL interop 参数陷阱 (只影响从 WSL 驱动探针, 不影响生产 insert)**: 传给 win exe 的
  **脚本路径实参**反斜杠会翻倍 (EINVAL), `-c` 实参不会; 探针用 `python.exe -c "runpy..."`
  载入。生产 insert 由 dsh host (win 原生 spawn) 直接起 python.exe, 无此层。
- **win python 文本 IO 默认 UTF-8 靠系统 locale**: 本机 Store python 默认 utf-8, 但
  非 UTF-8 locale 机器会按 ANSI 码页读写 registry.json (内含非 ASCII cwd)——insert env
  焊死 `PYTHONUTF8: '1'` 根治。
- **pyc 秒级 mtime 陷阱 (开发循环)**: 编辑后 1s 内重跑可能命中同秒 pyc 复用加载旧码
  (win 侧经 9P 编译 pyc 同理)——改 hub/common 后立即验证先清 `__pycache__`。
- 心跳/活性: 与 WSL 侧同语义 (MCP 进程存活=档位活性); hub `A2A_HUB_IDLE_REAP=1`
  时空闲 1h 自回收 (MCP 心跳/last_seen/队列三闲才退), 下次工具调用再拉起。

### wsl.exe 桥变体 (mailbox 根留 WSL 的主机机器)

command=`C:\Windows\System32\wsl.exe`, script/根全是 WSL 侧 POSIX 路径, MCP 进程落在
WSL 内——registry 锁 (fcntl)、原子写、hub 同侧, 零跨界文件系统。五键 env 经 `WSLENV`
逐键 `/u` 透传 (Windows→WSL env 不自动过境)。模板: `cordis.patch.win.yml`; 托管 host:
`bash deploy/dsh/dsh-host-win.sh` (需 `DSH_WIN_ROOT`/`WIN_USER`)。承重纪律:

- **agent_id 两处真相源**: `dsh-host-win.sh` 默认推导 `dsh-${A2A_HOST_TAG:-host-a}-win`,
  与 insert 档名是两处真相源——运行前先导出与 insert 一致的 `A2A_AGENT_ID` 或
  `A2A_HOST_TAG`, 不一致则 token 落错档名, `ensure_cookie` 缺 token 全量回弹。
- **token 落点按形态分叉**: 桥形态写 WSL 根 `~/.agents-mailbox/dsh-hosts/<agent_id>.token`
  0600 并清旧 `.cookie`——host 重启=新 token 旧 cookie 必失配, 不清则最长 27 天投递 401;
  纯 win 主形态则是另一处落点 (win 根 `<win-mailbox-root>\dsh-hosts\`)。
- **端口/进程纪律**: 端口被占即拒 (win 侧默认 3081, 与 WSL 侧 3080 错开); 60s 抓不到
  token 失败即杀 (按端口解析 pid `taskkill /T /F`); 停止按脚本打印的精确 pid
  `taskkill /PID <pid> /T /F`, 禁宽匹配。
- `DSH_WIN_ROOT`/`NODE_WIN_BIN`/`WIN_USER` 含空格即拒 (cmd /c 单参串内嵌引号经
  interop 不可靠), 用 8.3 短路径。

### 实测边界 (win 侧通用, 2026-11-12 本机活体)

- **mirrored loopback 双向**: win→WSL (8765 gateway) 通; WSL→win (3081 host) 通
  (dsh host 真节点实测)。注: Store python 经 `start /b` 起的监听进程 win 本机也连不上
  (疑似防火墙对非交互 spawn 的 RST), 判连通性务必用真节点。
- **writer-held 会话拒投**: 被浏览器等其他 writer 持有的会话, `session/prompt` 报
  `session/writer-held`——hub 走 queue 同族滞留重试 3 次后回弹, 属宿主所有权语义非缺陷;
  处方=投递目标选 host 自己连接建的会话, 或等浏览器释放。
- **interop 起后台进程防挂** (dsh-host-win.sh 的形态): WSL interop 等待全部 Windows 后代
  job——powershell `Start-Process -WindowStyle Hidden cmd` 脱离 job 调用即返; 同一串里
  `set PATH=...` 引旧值必须 `/v:on` + `!PATH!` 延迟展开; 引号经 interop/PS/cmd 多层解析
  不可靠, spawn 行只留一对 bash 双引号 + 一对 PS 单引号, 路径含空格一律 8.3 短路径。
  (dsh-host-win-native.ps1 是纯 win 侧执行, 不经这些层。)
- **共享 profile 二 host 互染**: insert 段焊死 `A2A_AGENT_ID`/`A2A_RPC_INBOX_URL`,
  同一 profile 的其他 dsh host (如 dev host) 经 HMR 吃到同一 insert, 会以同身份给指向
  该端口的档续命——host 停用/换端口后务必把 insert 段一并回退 (只清 token/cookie 不够),
  或按 host 实例独立 profile/overlay 绑定身份与端口。
- **session/prompt 的 mode**: running 会话 steer (插当前轮), idle 会话 queue (下一轮);
  blank 会话不被 pick——冒烟时先 session/create + prompt 一封使会话脱 blank。
- **dsh web host 的 token 随每次重启更换**——托管 host 脚本 (起即抓 token) 是主路径;
  上游建议 (用户自己项目): web 加固定 token 参数一行改动根治。

### 联邦 (win↔WSL 双 hub, 部署文档步骤)

本机 win 无 sshd (OpenSSH.Server State=NotPresent), 未装系统服务。若未来开联邦:
win 装 OpenSSH Server, win hub 侧 peers.json 指回 WSL (或反之); mirrored 网络下
win↔WSL 互通无需 tailscale, 但两侧 sshd 端口要错开 (win sshd 建议用非 22 端口, 如 2222);
host-b 的 dsh 档 `ssh_alias` 置联邦别名, 信由 home hub relay 归其本机 hub 直投。
