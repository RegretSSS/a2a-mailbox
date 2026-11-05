# a2a-mailbox

中文｜[English](README.en.md)

Cross-CLI agent messaging: let Claude Code / Codex / Pi / ZCode terminal agents message each other like email. File-based mailboxes with a resident delivery hub that picks the channel per recipient (tmux injection / native queue / daemon queue / pull), federated across hosts over ssh.

> Shares the name "A2A" with Google's Agent2Agent protocol — unrelated. This project is a file mailbox between terminal agents, not a protocol implementation.

```
┌─────────────┐  mail_send   ┌──────────────┐  pick channel ┌─────────────┐
│  agent A    │ ───────────▶ │   mailbox    │ ───────────▶  │  agent B    │
│ (CC, pi:xA) │ ◀─────────── │  queue+hub   │ ◀──────────── │ (codex,pi:yB)│
└─────────────┘ reply/ack    └──────┬───────┘ wake / queue  └─────────────┘
                                 hub daemon
                     inject-confirm·receipt·retry·bounce
                     dual send-locks (scope/group)
                          federation pull (ssh)
                                 ┌────┴───────┐
                                 │ remote hub  │
                                 └────────────┘
```

## Channel matrix

The hub picks a delivery channel by recipient shape:

| Recipient | Channel | Mechanism |
|---|---|---|
| Claude Code | tmux injection | probe idle input → paste wake word → stepped Enter → frame-level echo confirm, backoff retries |
| Pi | native inbox | `a2a-inbox.ts` extension queue (sendUserMessage), receipt + heartbeat, falls back to tmux when absent |
| Codex (WSL) | daemon queue | `codex queue --thread` via the app-server daemon, deterministic receipt (`Queued message <uuid>`) |
| Codex (native Windows) | daemon queue | WSL hub invokes codex.exe across interop; or a pure-Windows node invokes it locally |
| ZCode | pull-only | no injection path; mail waits in queue for its `mail_poll` |
| Cross-host | federation | sender hub ssh-writes the remote queue directly; registries merge via pull; stale copies kept across outages |

Failure semantics: queue-channel failures retry in place (60s throttle, max 3) then bounce — **never degrade to tmux** (prevents typing into the wrong window); fallback mail from failed direct writes goes through a relay-retry chain (60s throttle, 1800s give-up).

## Tools

Standard mounting (MCP stdio):

```json
{
  "mcpServers": {
    "mailbox": { "command": "python3", "args": ["<abs path to this repo>/mcp/mailbox_mcp.py"] }
  }
}
```

Six tools (default surface is fixed; Docker deployments expose the same set):

| Tool | Purpose |
|---|---|
| `mail_send(to, body, in_reply_to?, context?, expect_reply?)` | Send. `in_reply_to` auto-acks the original (reply-implies-ack); `expect_reply=true` appends `[需回函]` to the wake word |
| `mail_poll()` | List own pending message summaries (non-consuming) |
| `mail_read(msg_id)` | Read full body (includes `ack_id`; falls through to federation peers on local miss) |
| `mail_ack(ack_id)` | Business ack (idempotent; self-attested on disk when cross-host) |
| `mail_who(all?)` | Registered agents + federation peer status (group-only markers/member counts); live agents only by default (stale filtered to keep the roster sane), `all=true` includes them; same-directory instances get their own `id@instance-prefix` rows, usable directly as recipients |
| `mail_group(action, agent_id?, note?, group?, group_only?)` | Group permissions, five actions in one dispatcher: `join` request joining a recipient (`agent_id`=gatekeeper, `note`=intent) / `pending` list your own pending requests / `admit` allow `agent_id` to mail you / `revoke` remove / `gate` toggle your admitted-senders-only gate (`group_only=true` on, `group`=display name). The default tool surface stays at exactly six |



## Permission model (three-tier subagent isolation + group admission)

Subagents and workflow-spawned agents inherit the host's MCP tool surface and can send in its name. Three tiers, in order of preference:

1. **Deny at definition (preferred)**: leave `mcp__mailbox__*` out of the subagent's tool allowlist (CC example in `snippets/claude-code/subagent-no-mailbox.md`; likewise for Pi/codex subagent configs). No tool, no attack surface — a subagent's cross-CLI egress goes through its main, internal collaboration uses each CLI's own machinery.
2. **Scope lock (fallback)**: covers inherit-everything cases that cannot be allowlisted (built-in default subagents, workflow default agents) — give such a mailbox instance `A2A_PEER_OF=<main agent_id>`; it may only exchange with its main agent, anything else is rejected on the spot (`subagent 发送锁`). The lock lives in the registry and survives restarts.
3. **Hub delivery re-check (always on)**: independent of whether MCP is mounted — mail written straight into the queue bypassing the tool surface is equally rejected/bounced by the scope/group re-check.

**Group admission**: after `mail_group(action=gate, group_only=true)`, only admitted senders may mail you; others go through `mail_group(action=join)` (a side channel, not gated) and the gatekeeper's `mail_group(action=admit, agent_id=…)`. Hub bounces are exempt (so failure mail always reaches you).

Roster stays lean: `mail_who` rows carry short markers only (`group=<name>`, `group_only`, `members=<count>`, `subagent_of=<main>`); the full admission list is visible only to the agent itself.

## Getting started (Linux / WSL, five minutes)

1. Requires Python 3.11+, `pip install fastmcp`, tmux (Pi channel needs the extension in `pi/a2a-inbox.ts`). One-shot env check + mounting-config generation: `bash scripts/bootstrap.sh` (add `--apply` to auto-install python deps, `--project <dir>` to write `.mcp.json` directly).
2. Mount the MCP (Claude Code example; other CLIs see `snippets/`):

   ```json
   {
     "mcpServers": {
       "mailbox": { "command": "python3", "args": ["<abs path to this repo>/mcp/mailbox_mcp.py"] }
     }
   }
   ```

3. Start your agent inside a tmux window with MCP enabled — the first mail tool call self-registers (the hub is booted automatically if absent).
4. `mail_who()` to see each other, then `mail_send()`.

Quickest verification path (two agents, one machine): start two CLIs in two tmux windows (e.g. one Claude Code + one Pi), have each call `mail_who` once (triggers self-registration), then `mail_send(to="<other id>", body="ping")` — the recipient gets the wake message; a reply closes the loop. For cross-host, add `scripts/add-peer.sh` (see "Cross-host federation").

**Codex auto-anchoring**: Codex MCP servers are hosted by the app-server daemon (ancestor-based anchoring is structurally blind there), so registration reverse-anchors the TUI — scan tmux for the `codex` process whose cwd uniquely matches, take pane+thread. Native-Windows Codex is located by scanning `/mnt/<drive>/Users/*/.codex/sessions` rollout headers for the cwd (newest session wins across profiles).

**Subagent isolation**: prefer leaving mailbox out of the agent's tool allowlist (see `snippets/claude-code/subagent-no-mailbox.md`); for inherit-everything instances that cannot be allowlisted, add `"env": {"A2A_PEER_OF": "<main agent_id>"}` to their mailbox instance to restrict it to its main agent.

**Multiple instances in one directory**: agent_id is derived as `{cli}-{host}-{dir slug}` — two instances on the same host sharing a directory with the same (unknown) CLI detection share one identity (registry overwrites, replies go to whichever registered first). When more than one instance shares a working directory, give each mailbox `"env": {"A2A_AGENT_ID": "<custom id>"}` to split them explicitly; hub-side cwd re-anchoring verifies the pane's foreground command, so unknown records never get dragged onto a local tmux pane. claude/pi additionally have a native instance channel: same-cli same-directory double-start no longer rejects — registration files an instances table keyed by the first 8 chars of `CLAUDE_CODE_SESSION_ID` (pi: pane id), `mail_who` lists `id@instance-prefix` rows, and `mail_send(to="id@instance-prefix")` targets that instance's window; when CC compact changes the session id, the same-pane old instance entry is replaced automatically (mailbox untouched). **Offline auto-revival**: sending to a local claude/pi record that is confirmed offline (not merely unknown) first revives the conversation per its spec'd recipe — claude = tmux respawn of its fixed window with `claude -c`, pi = direct background start; codex is positioned as the controller and is never auto-revived.

## Pure Windows node (no WSL, experimental)

A node without tmux works too — usable channels: Codex queue-daemon (direct codex.exe) + ZCode pull + the full MCP tool surface (Claude Code / Pi injection channels unavailable). **Experimental**: the pure-Windows path has only been verified on a single physical machine (UNC-path storage, interop avoidance); feedback welcome.

1. Requires Python 3.11+, `pip install fastmcp`, OpenSSH client (for federation).
2. Mount the MCP as above (full path to `python.exe`).
3. Set `A2A_HUB_IDLE_REAP=1`: the hub runs as an independent process (booted by the first MCP call, not an MCP child) and exits when every MCP is offline and it is truly idle (no in-flight mail, agents aged 1h, heartbeat aged 1h); the next MCP call boots it again — no service supervisor needed.

## ZCode watch integration (workflow-based receiving)

ZCode has no MCP injection channel; a resident dynamic workflow stands in instead (ready-made skill in `snippets/zcode-watch-skill/`: SKILL.md + template.dwf.ts, with ack dedup, same-mail circuit breaker, 24-round bounded loop, and a relay persona that never executes mail instructions nor ghost-writes replies):

1. Edit the two constants atop the template: `AGENT_ID` (this session's identity, `zcode-<host>-<slug>`) and `BASE` (the WSL-side mailbox root).
2. `CreateWorkflow` pointing at the template — `world.run` watches the queue (`queue/<id>/*.msg`); on arrival the mail is escalated into the main session.
3. Answering the `MAIL|from=…|msgId=…|body=…` escalation counts as the delivery receipt (the relay then touches `acks/ack-<msg_id>` and archives the file); replies are written by the controller via `scripts/mail-send.py`. On round exhaustion or circuit breaker, re-arm per the completion notice.

## Cross-host federation

1. Exchange passwordless ssh aliases between hosts (`~/.ssh/config`).
2. Run `scripts/add-peer.sh <peer alias>` on each side to record it in `peers.json`.
3. Hubs pull and merge peer registries every 60s; mail to remote agents is ssh-written straight into the remote queue by the local hub; acks converge via federation lookups. Outages only warn and keep stale records; links resume automatically.

## Boundaries

- Trust domain = local user + passwordless ssh peers; no built-in authentication, do not expose to untrusted networks.
- All protocol state is forensically readable from `~/.agents-mailbox/` (registry / queue / history / acks / join-requests / hub.log).
- Two agents on one tmux seat are rejected; renames and window restarts are followed automatically (slot re-anchoring verifies the foreground process identity — a stranger process squatting a same-named window is refused, preventing wrong-window injection).
- Tests: `python3 -m pytest tests/ -q`; structural/behavioral assertions: `bash scripts/run-lints.sh`.

## License

Apache-2.0 (see [LICENSE](LICENSE)).
