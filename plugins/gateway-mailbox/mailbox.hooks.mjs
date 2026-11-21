import fs from "node:fs"
import os from "node:os"
import path from "node:path"

const AGENT_TO_CLI = [
  ["claude", "claude"],
  ["codex", "codex"],
  ["pi", "pi"],
]

const heartbeatMemory = new Map()
const notifyMemory = new Map()
const registryCaches = new Map()
const REGISTRY_CACHE_TTL_MS = 2000

function resolveRoot(options) {
  const raw = typeof options?.mailboxRoot === "string" && options.mailboxRoot ? options.mailboxRoot : "~/.agents-mailbox"
  const expanded = raw.startsWith("~") ? path.join(os.homedir(), raw.slice(1)) : raw
  return path.resolve(expanded)
}

function cliNameFor(agent) {
  if (agent.startsWith("claude")) return "claude"
  for (const [needle, cli] of AGENT_TO_CLI) {
    if (agent === needle) return cli
  }
  return null
}

function loadAgents(root) {
  const registryPath = path.join(root, "registry.json")
  let stat
  try {
    stat = fs.statSync(registryPath)
  } catch {
    return null
  }
  const now = Date.now()
  const cached = registryCaches.get(root)
  if (cached && cached.agents && stat.mtimeMs === cached.mtimeMs && now - cached.loadedAtMs < REGISTRY_CACHE_TTL_MS) {
    return cached.agents
  }
  try {
    const parsed = JSON.parse(fs.readFileSync(registryPath, "utf8"))
    registryCaches.set(root, { mtimeMs: stat.mtimeMs, loadedAtMs: now, agents: parsed?.agents ?? {} })
    return parsed?.agents ?? {}
  } catch {
    return null
  }
}

function mailboxIdFor(root, agent, cwd) {
  if (!cwd) return null
  const cli = cliNameFor(agent)
  if (!cli) return null
  const agents = loadAgents(root)
  if (!agents) return null
  const hits = Object.entries(agents)
    .filter(([, record]) => String(record?.cwd ?? "") === cwd && String(record?.cli ?? "") === cli)
    .map(([agentId]) => agentId)
    .sort()
  return hits[0] ?? null
}

function pendingCount(root, mailboxId) {
  const queueDir = path.join(root, "queue", mailboxId)
  try {
    return fs.readdirSync(queueDir).filter((name) => name.endsWith(".msg")).length
  } catch {
    return 0
  }
}

function writeHeartbeat(root, agent, session, cwd, heartbeatTtlSeconds) {
  const now = Date.now()
  const sessionKey = `${agent}|${session}`
  const last = heartbeatMemory.get(sessionKey) ?? 0
  if (now - last < 30_000) return
  heartbeatMemory.set(sessionKey, now)
  const heartbeatPath = path.join(root, "magpie-bridge.json")
  let state = { sessions: {}, agents: {} }
  try {
    state = JSON.parse(fs.readFileSync(heartbeatPath, "utf8"))
    if (!state || typeof state !== "object" || !state.sessions || !state.agents) state = { sessions: {}, agents: {} }
  } catch {}
  state.sessions ??= {}
  state.agents ??= {}
  const cutoff = now - heartbeatTtlSeconds * 1000
  for (const [key, record] of Object.entries(state.sessions)) {
    if (Number(record?.ts ?? 0) < cutoff) delete state.sessions[key]
  }
  for (const [key, ts] of Object.entries(state.agents)) {
    if (Number(ts ?? 0) < cutoff) delete state.agents[key]
  }
  state.sessions[sessionKey] = { cwd, ts: now }
  state.agents[agent] = now
  const tmpPath = `${heartbeatPath}.tmp-${process.pid}`
  try {
    fs.writeFileSync(tmpPath, JSON.stringify(state))
    fs.renameSync(tmpPath, heartbeatPath)
  } catch {}
}

function notifyText(mailboxId, count) {
  return `[A2A] mailbox: ${count} 封待读信（${mailboxId}）。完成当前步骤后调 mail_poll() 处理，勿中断当前任务。`
}

function injectUserMessage(body, protocol, text) {
  if (protocol === "responses") {
    if (!Array.isArray(body.input)) return undefined
    body.input.push({ type: "message", role: "user", content: [{ type: "input_text", text }] })
    return body
  }
  if (protocol === "gemini") {
    if (!Array.isArray(body.contents)) return undefined
    body.contents.push({ role: "user", parts: [{ text }] })
    return body
  }
  if (!Array.isArray(body.messages)) return undefined
  body.messages.push({ role: "user", content: text })
  return body
}

export async function onRequest(body, ctx) {
  try {
    const root = resolveRoot(ctx.options)
    const agent = String(ctx.agent ?? "")
    const session = String(ctx.session ?? "")
    const cwd = String(ctx.cwd ?? "")
    const cooldownMs = Math.max(Number(ctx.options?.notifyCooldownSeconds ?? 60), 5) * 1000
    const heartbeatTtl = Math.max(Number(ctx.options?.heartbeatTtlSeconds ?? 600), 60)
    writeHeartbeat(root, agent, session, cwd, heartbeatTtl)
    if (!cwd || !session) return undefined
    const mailboxId = mailboxIdFor(root, agent, cwd)
    if (!mailboxId) return undefined
    const pending = pendingCount(root, mailboxId)
    if (!pending) return undefined
    const notifyKey = `${agent}|${session}`
    const lastNotify = notifyMemory.get(notifyKey) ?? 0
    if (Date.now() - lastNotify < cooldownMs) return undefined
    notifyMemory.set(notifyKey, Date.now())
    return injectUserMessage(body, ctx.protocol, notifyText(mailboxId, pending))
  } catch {
    return undefined
  }
}
