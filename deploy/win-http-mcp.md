# win codex 挂 http MCP 材料（host-b 冻结解除时用）

前置：host-b WSL 侧 `scripts/deploy-host-b.sh` 已跑过一次（代码与 systemd 就位），hub 存活。

## 1. WSL 侧起网关

```bash
cp deploy/a2a-mailbox-http.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now a2a-mailbox-http.service
curl -s http://127.0.0.1:8765/healthz
```

healthz 列出全部在册档即就绪。tailscale 联邦开放（跨机查询面）时：

```bash
# 写 token（非 loopback bind 强制）
openssl rand -hex 24 > ~/.agents-mailbox/http-token
systemctl --user edit a2a-mailbox-http.service   # 加 A2A_MCP_HTTP_BIND=0.0.0.0
systemctl --user restart a2a-mailbox-http.service
```

## 2. win 侧 portproxy（管理员 PowerShell）

WSL IP 变更后需重跑（`wsl hostname -I` 取新 IP）：

```powershell
$wslIp = (wsl hostname -I).Trim().Split()[0]
netsh interface portproxy add v4tov4 listenaddress=127.0.0.1 listenport=8765 connectaddress=$wslIp connectport=8765
netsh advfirewall firewall add rule name="a2a-mailbox http" dir=in action=allow protocol=TCP localport=8765
```

仅 win 本机回环访问不需要防火墙规则；portproxy 指向 127.0.0.1:8765 时 bind 保持 loopback 即可，无需 token。

## 3. codex 换连接（win 侧 cmd/PowerShell）

每个 win codex 档一条，`<agent_id>` 取 healthz 列表中的档名：

```
codex mcp remove mailbox
codex mcp add mailbox --url http://127.0.0.1:8765/<agent_id>/mcp
```

重启 codex 后工具面走 http；信箱注册、hub 投递、联邦全不动。

## 4. 回退

```
codex mcp remove mailbox
codex mcp add mailbox -- <原 stdio 命令>
```

portproxy 清理：`netsh interface portproxy delete v4tov4 listenaddress=127.0.0.1 listenport=8765`。
