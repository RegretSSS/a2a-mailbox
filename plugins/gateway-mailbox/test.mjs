import assert from "node:assert/strict"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import test from "node:test"

import { onRequest } from "./mailbox.hooks.mjs"

function makeRoot(t, agents, queueFiles = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "mb-hook-"))
  t.after(() => fs.rmSync(root, { recursive: true, force: true }))
  fs.writeFileSync(path.join(root, "registry.json"), JSON.stringify({ agents }))
  for (const [mailboxId, files] of Object.entries(queueFiles)) {
    const dir = path.join(root, "queue", mailboxId)
    fs.mkdirSync(dir, { recursive: true })
    for (const name of files) fs.writeFileSync(path.join(dir, name), "{}")
  }
  return root
}

function ctx(root, agent, session, cwd, protocol = "anthropic") {
  return { agent, session, cwd, protocol, model: "m", options: { mailboxRoot: root, notifyCooldownSeconds: 60, heartbeatTtlSeconds: 600 }, state: {}, signal: new AbortController().signal, report: () => {} }
}

const AGENTS = {
  "codex-host-a-a2a-mailbox": { cli: "codex", cwd: "/home/u/w/a2a-mailbox" },
  "claude-host-a-other": { cli: "claude", cwd: "/home/u/w/other" },
}

test("pending mail notifies once then cooldown holds", async (t) => {
  const root = makeRoot(t, AGENTS, { "codex-host-a-a2a-mailbox": ["a.msg"] })
  const body = { messages: [{ role: "user", content: "hi" }] }
  const first = await onRequest({ ...body, messages: [...body.messages] }, ctx(root, "codex", "s1", "/home/u/w/a2a-mailbox"))
  assert.ok(first.messages.at(-1).content.includes("1 封待读信"))
  assert.ok(first.messages.at(-1).content.includes("mail_poll"))
  const second = await onRequest({ ...body, messages: [...body.messages] }, ctx(root, "codex", "s1", "/home/u/w/a2a-mailbox"))
  assert.equal(second, undefined)
  const bridge = JSON.parse(fs.readFileSync(path.join(root, "magpie-bridge.json"), "utf8"))
  assert.equal(bridge.sessions["codex|s1"].cwd, "/home/u/w/a2a-mailbox")
  assert.ok(bridge.agents.codex > 0)
})

test("empty queue never notifies", async (t) => {
  const root = makeRoot(t, AGENTS)
  const result = await onRequest({ messages: [] }, ctx(root, "codex", "s2", "/home/u/w/a2a-mailbox"))
  assert.equal(result, undefined)
})

test("cwd without matching record never notifies", async (t) => {
  const root = makeRoot(t, AGENTS, { "codex-host-a-a2a-mailbox": ["a.msg"] })
  const result = await onRequest({ messages: [] }, ctx(root, "codex", "s3", "/home/u/w/nowhere"))
  assert.equal(result, undefined)
})

test("agent outside cli families never notifies even with cwd match", async (t) => {
  const root = makeRoot(t, AGENTS, { "codex-host-a-a2a-mailbox": ["a.msg"] })
  const result = await onRequest({ messages: [] }, ctx(root, "curl", "s4", "/home/u/w/a2a-mailbox"))
  assert.equal(result, undefined)
})

test("claude prefix family matches claude-code style agent names", async (t) => {
  const root = makeRoot(t, { "claude-host-a-other": { cli: "claude", cwd: "/home/u/w/other" } }, { "claude-host-a-other": ["b.msg"] })
  const result = await onRequest({ messages: [] }, ctx(root, "claude-code", "s5", "/home/u/w/other"))
  assert.ok(result.messages.at(-1).content.includes("claude-host-a-other"))
})

test("responses protocol appends typed input item", async (t) => {
  const root = makeRoot(t, AGENTS, { "codex-host-a-a2a-mailbox": ["a.msg"] })
  const result = await onRequest({ input: [{ type: "message", role: "user", content: [] }] }, ctx(root, "codex", "s6", "/home/u/w/a2a-mailbox", "responses"))
  assert.equal(result.input.at(-1).type, "message")
  assert.equal(result.input.at(-1).role, "user")
  assert.equal(result.input.at(-1).content[0].type, "input_text")
})

test("gemini protocol appends contents part", async (t) => {
  const root = makeRoot(t, { "pi-host-a-notes": { cli: "pi", cwd: "/home/u/w/notes" } }, { "pi-host-a-notes": ["c.msg"] })
  const result = await onRequest({ contents: [{ role: "user", parts: [{ text: "x" }] }] }, ctx(root, "pi", "s7", "/home/u/w/notes", "gemini"))
  assert.equal(result.contents.at(-1).parts[0].text.includes("pi-host-a-notes"), true)
})

test("missing message array returns undefined untouched", async (t) => {
  const root = makeRoot(t, AGENTS, { "codex-host-a-a2a-mailbox": ["a.msg"] })
  const result = await onRequest({ model: "m" }, ctx(root, "codex", "s8", "/home/u/w/a2a-mailbox"))
  assert.equal(result, undefined)
})

test("queue files untouched after many requests", async (t) => {
  const root = makeRoot(t, AGENTS, { "codex-host-a-a2a-mailbox": ["a.msg", "b.msg"] })
  for (let i = 0; i < 5; i++) {
    await onRequest({ messages: [] }, ctx(root, "codex", `s9-${i}`, "/home/u/w/a2a-mailbox"))
  }
  assert.deepEqual(fs.readdirSync(path.join(root, "queue", "codex-host-a-a2a-mailbox")).sort(), ["a.msg", "b.msg"])
})

test("stale heartbeat sessions pruned by ttl", async (t) => {
  const root = makeRoot(t, AGENTS)
  await onRequest({ messages: [] }, ctx(root, "codex", "fresh", "/home/u/w/a2a-mailbox"))
  const bridgePath = path.join(root, "magpie-bridge.json")
  const stale = JSON.parse(fs.readFileSync(bridgePath, "utf8"))
  stale.sessions["codex|ancient"] = { cwd: "/x", ts: Date.now() - 11 * 60 * 1000 }
  fs.writeFileSync(bridgePath, JSON.stringify(stale))
  await onRequest({ messages: [] }, ctx(root, "pi", "another", "/home/u/w/notes"))
  const after = JSON.parse(fs.readFileSync(bridgePath, "utf8"))
  assert.equal(after.sessions["codex|ancient"], undefined)
  assert.ok(after.sessions["pi|another"])
})

test("record cli field wins over agent_id prefix mismatch", async (t) => {
  const root = makeRoot(t, { "claude-host-a-legacy": { cli: "codex", cwd: "/home/u/w/legacy" } }, { "claude-host-a-legacy": ["x.msg"] })
  const result = await onRequest({ messages: [] }, ctx(root, "codex", "s10", "/home/u/w/legacy"))
  assert.ok(result.messages.at(-1).content.includes("claude-host-a-legacy"))
})
