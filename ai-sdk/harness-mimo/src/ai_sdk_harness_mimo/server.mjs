// ACP-over-stdio server wrapping the AI SDK 7 HarnessAgent driven by MiMo's
// native `mimo acp` server. MiMo Code (OpenCode fork) is itself a complete ACP
// agent, so — unlike createPi/createCodex which wrap a JS-library loop — the
// HarnessAgent here runs a thin custom HarnessV1 adapter (`createMimo`) whose
// doStart spawns `mimo acp` on the HOST (writable stdin; the harness sandbox's
// SandboxProcess has none) and bridges its ACP JSON-RPC to HarnessV1 stream
// parts. Two ACP layers: benchflow <-> this server (outer), and this server's
// HarnessAgent adapter <-> `mimo acp` (inner). Feasibility proven by spike.
//
// MiMo composes a per-session working dir <root>/mimo-<sessionId>; benchflow's
// task files + verifier live in the task cwd. So we BRIDGE (as harness-pi does):
// seed the task files into the session dir before the turn, sync results back
// after — so MiMo operates on the real task and the verifier sees the output.
import { createInterface } from "node:readline";
import { spawn } from "node:child_process";
import {
  cpSync, readdirSync, mkdirSync, mkdtempSync, existsSync,
  createReadStream, writeFileSync,
} from "node:fs";
import * as fsp from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { Readable } from "node:stream";
import { HarnessAgent, HarnessCapabilityUnsupportedError } from "@ai-sdk/harness/agent";

for (const k of ["HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy",
                 "NO_PROXY", "no_proxy", "NODE_TLS_REJECT_UNAUTHORIZED"]) delete process.env[k];

// The mimo CLI launcher is `#!/usr/bin/env node`; the sandbox launch invokes
// us by absolute node path with node NOT on PATH (only /opt/benchflow/node/bin
// has it, no system node), so the launcher's shebang fails — `env: node: not
// found` → the child exits 127 → 0 tokens/0 tools → suspected_api_error. Put
// our own node dir on PATH so every child we spawn (mimo + bash tools) finds it.
process.env.PATH = dirname(process.execPath) + (process.env.PATH ? ":" + process.env.PATH : "");

// Belt-and-suspenders: a long-lived ACP server must ALWAYS return a result to
// benchflow rather than let a stray async error (e.g. an EPIPE from a dead inner
// child) exit the process mid-turn — a crashed transport nulls the whole run. The
// targeted child-death handling in makeAcpClient prevents these; this only
// guarantees no late/stray rejection ever takes the process down.
process.on("uncaughtException", (e) => log("uncaughtException (ignored):", String((e && e.stack) || e)));
process.on("unhandledRejection", (e) => log("unhandledRejection (ignored):", String((e && e.stack) || e)));

const MIMO_BIN = process.env.MIMO_BIN
  || join("/opt/benchflow/js-agents/ai-sdk-mimo", "node_modules", ".bin", "mimo");
const log = (...a) => process.stderr.write("[ai-sdk-harness-mimo] " + a.join(" ") + "\n");
const RESULT_MAX = 2000, TITLE_MAX = 800;
function send(m) { process.stdout.write(JSON.stringify(m) + "\n"); }
function notify(u) { send({ jsonrpc: "2.0", method: "session/update", params: { sessionId, update: u } }); }

let sessionId = "ai-sdk-harness-mimo-1";
let agentCwd = process.cwd();
let modelId = process.env.BENCHFLOW_PROVIDER_MODEL || "";
let harnessSession = null, sessionDir = null, currentAbort = null, cachedAgent = null;

const isMimoDir = (n) => /^mimo-/.test(n);
// `.daytona` is Daytona's root-owned per-sandbox infra dir living in the task
// cwd; copying it into the session dir makes mimo's own session writes fail with
// EACCES under the non-root sandbox agent user. Skip it (mimo creates a fresh,
// writable one). Per-entry try/catch so one un-copyable entry can't abort seeding.
const SKIP_SEED = new Set([".daytona"]);
const seedIntoSession = () => {                       // task files -> session dir
  for (const e of readdirSync(agentCwd, { withFileTypes: true })) {
    if (isMimoDir(e.name) || e.isSymbolicLink() || SKIP_SEED.has(e.name)) continue;
    try { cpSync(join(agentCwd, e.name), join(sessionDir, e.name), { recursive: true }); }
    catch (err) { log("seed skip", e.name, String(err).slice(0, 120)); }
  }
};
const syncBackToCwd = () => {                          // agent results -> task cwd
  try {
    for (const e of readdirSync(sessionDir, { withFileTypes: true }))
      cpSync(join(sessionDir, e.name), join(agentCwd, e.name), { recursive: true });
  } catch (e) { log("sync-back error:", String(e)); }
};

// ── inner ACP JSON-RPC client over the `mimo acp` child's stdio ──────────────
function makeAcpClient(child) {
  let buf = "";
  let nextId = 1;
  let dead = false;
  const pending = new Map();
  const notifyHandlers = new Set();
  const serverRequestHandlers = new Set();
  // Reject every in-flight request the moment the `mimo acp` child dies. A
  // mid-turn death (OOM-kill in the 2GB sandbox, crash, lost egress) otherwise
  // leaves session/prompt awaiting forever (hang) AND lets a later stdin write
  // EPIPE-crash this process (rc=255) — both null the benchflow run. Mirrors the
  // omnigent _mimo_acp.py _fail_pending-on-EOF contract.
  const failPending = (why) => {
    if (dead) return;
    dead = true;
    const e = new Error("mimo acp child gone: " + why);
    for (const [, pr] of pending) { try { pr.reject(e); } catch {} }
    pending.clear();
  };
  child.on("error", (e) => { log("mimo child error:", String(e)); failPending("child error: " + String(e)); });
  child.on("exit", (code, sig) => { log(`mimo child exit code=${code} sig=${sig}`); failPending(`exited code=${code} sig=${sig}`); });
  child.stdout.on("close", () => failPending("stdout closed"));
  child.stdin.on("error", () => {});   // never let an EPIPE on the child pipe go unhandled
  // A write that can never throw — a write to a dead child must not crash us.
  const write = (obj, onFail) => {
    if (dead || !child.stdin.writable) { if (onFail) onFail(new Error("mimo acp child not writable")); return false; }
    try { child.stdin.write(JSON.stringify(obj) + "\n"); return true; }
    catch (e) { failPending("write failed: " + String(e)); if (onFail) onFail(e); return false; }
  };
  child.stdout.on("data", (d) => {
    buf += d;
    let i;
    while ((i = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, i).trim();
      buf = buf.slice(i + 1);
      if (!line) continue;
      let m;
      try { m = JSON.parse(line); } catch { continue; }
      if (m.id != null && pending.has(m.id)) {
        const pr = pending.get(m.id); pending.delete(m.id);
        m.error ? pr.reject(new Error(JSON.stringify(m.error))) : pr.resolve(m.result);
      } else if (m.method && m.id != null) {
        for (const h of serverRequestHandlers) { try { h(m); } catch (e) { log("server-req handler:", String(e)); } }
      } else if (m.method) {
        for (const h of notifyHandlers) { try { h(m); } catch (e) { log("notify handler:", String(e)); } }
      }
    }
  });
  return {
    request(method, params) {
      return new Promise((resolve, reject) => {
        if (dead) { reject(new Error("mimo acp child not available")); return; }
        const id = nextId++;
        pending.set(id, { resolve, reject });
        write({ jsonrpc: "2.0", id, method, params }, (e) => { pending.delete(id); reject(e); });
      });
    },
    notify(method, params) { write({ jsonrpc: "2.0", method, params }); },
    reply(id, result) { write({ jsonrpc: "2.0", id, result }); },
    onNotification(h) { notifyHandlers.add(h); },
    onServerRequest(h) { serverRequestHandlers.add(h); },
    isDead: () => dead,
  };
}
function textOf(content) {
  if (content == null) return "";
  if (typeof content === "string") return content;
  if (Array.isArray(content)) return content.map(textOf).join("");
  if (content.type === "text") return content.text ?? "";
  if (content.type === "content") return textOf(content.content);
  if (content.content != null) return textOf(content.content);
  if (content.text != null) return content.text;
  return "";
}

// ── createMimo(): the HarnessV1 adapter (plain literal, no in-sandbox bridge) ─
function createMimo(settings = {}) {
  return {
    specificationVersion: "harness-v1",
    harnessId: "mimo",
    builtinTools: {},
    supportsBuiltinToolApprovals: false,
    doStart: async (startOpts) => createMimoSession({ startOpts, settings }),
  };
}

async function createMimoSession({ startOpts, settings }) {
  const cwd = startOpts.sessionWorkDir;
  // Proxy mode (usage_tracking != off): benchflow points OPENAI_BASE_URL at its
  // LiteLLM usage proxy and sends the model as the `benchflow-*` alias. mimo
  // rejects that id via models.dev — UNLESS it is a custom provider. So register
  // a custom OpenAI-compatible provider "benchflow" at the proxy and route the
  // turn as `benchflow/<alias>`; mimo then POSTs to the proxy, which captures
  // trajectory/llm_trajectory.jsonl (raw prompts/completions + per-request tokens).
  let innerModel = settings.model;
  const proxyBase = process.env.OPENAI_BASE_URL;
  if (proxyBase && settings.model) {
    const alias = settings.model.includes("/") ? settings.model.split("/").pop() : settings.model;
    try {
      const cfgDir = join(cwd, ".mimocode");
      mkdirSync(cfgDir, { recursive: true });
      writeFileSync(join(cfgDir, "mimocode.json"), JSON.stringify({
        "$schema": "https://opencode.ai/config.json",
        provider: {
          benchflow: {
            npm: "@ai-sdk/openai-compatible",
            name: "BenchFlow Proxy",
            options: { baseURL: proxyBase, apiKey: process.env.OPENAI_API_KEY || "benchflow" },
            models: { [alias]: { name: alias } },
          },
        },
      }, null, 2));
      innerModel = "benchflow/" + alias;
      log("proxy mode: wrote custom provider, inner model =", innerModel);
    } catch (e) { log("proxy provider write failed (falling back to native):", String(e).slice(0, 160)); }
  }
  const child = spawn(MIMO_BIN, ["acp", "--cwd", cwd], {
    stdio: ["pipe", "pipe", "pipe"],
    env: { ...process.env, ...(settings.env ?? {}) },
  });
  child.stderr.on("data", (d) => process.stderr.write("[mimo] " + d));
  const rpc = makeAcpClient(child);
  await rpc.request("initialize", {
    protocolVersion: 1,
    clientCapabilities: { fs: { readTextFile: true, writeTextFile: true }, terminal: false },
  });
  const ns = await rpc.request("session/new", { cwd, mcpServers: [] });
  const acpSid = ns.sessionId;
  if (settings.model) {
    try { await rpc.request("session/set_model", { sessionId: acpSid, modelId: innerModel }); }
    catch (e) { log("inner set_model failed, using default:", String(e).slice(0, 160)); }
  }
  // Auto-allow permission prompts (the dedicated sandbox is the isolation boundary).
  rpc.onServerRequest((m) => {
    if (typeof m.method === "string" && m.method.includes("permission")) {
      const opt = m.params?.options?.find((o) => /allow|approve|yes/i.test(o.optionId || o.name || ""))
        ?? m.params?.options?.[0];
      rpc.reply(m.id, { outcome: { outcome: "selected", optionId: opt?.optionId ?? "allow" } });
    } else { rpc.reply(m.id, {}); }
  });

  let currentEmit = null;
  let instructionsApplied = startOpts.continueFrom != null || startOpts.resumeFrom != null;
  const openText = new Set(), openReasoning = new Set();
  rpc.onNotification((m) => {
    if (m.method !== "session/update") return;
    const u = m.params?.update;
    if (!u || !currentEmit) return;
    switch (u.sessionUpdate) {
      case "agent_message_chunk": {
        const id = u.messageId ?? "msg";
        if (!openText.has(id)) { currentEmit({ type: "text-start", id }); openText.add(id); }
        currentEmit({ type: "text-delta", id, delta: textOf(u.content) });
        break;
      }
      case "agent_thought_chunk": {
        const id = u.messageId ?? "think";
        if (!openReasoning.has(id)) { currentEmit({ type: "reasoning-start", id }); openReasoning.add(id); }
        currentEmit({ type: "reasoning-delta", id, delta: textOf(u.content) });
        break;
      }
      case "tool_call":
        currentEmit({
          type: "tool-call", toolCallId: u.toolCallId, toolName: u.title ?? "tool",
          input: JSON.stringify(u.rawInput ?? u.input ?? {}), providerExecuted: true, nativeName: u.title,
        });
        break;
      case "tool_call_update":
        if (u.status === "completed" || u.status === "failed")
          currentEmit({
            type: "tool-result", toolCallId: u.toolCallId, toolName: u.title ?? "tool",
            result: textOf(u.content) || u.status, isError: u.status === "failed", providerExecuted: true,
          });
        break;
      default: break;
    }
  });

  const mapUsage = (usage = {}) => ({
    inputTokens: { total: usage.inputTokens ?? 0, cacheRead: usage.cachedReadTokens },
    outputTokens: { total: usage.outputTokens ?? 0, reasoning: usage.thoughtTokens },
  });
  const extractUserText = (prompt) => {
    if (typeof prompt === "string") return prompt;
    const c = prompt?.content;
    if (typeof c === "string") return c;
    if (Array.isArray(c)) return c.filter((p) => p?.type === "text").map((p) => p.text).join("");
    return String(prompt ?? "");
  };

  function runTurn({ text, emit, abortSignal }) {
    currentEmit = emit;
    openText.clear(); openReasoning.clear();
    emit({ type: "stream-start", modelId: settings.model ?? ns.models?.currentModelId });
    const turn = (async () => {
      try {
        const res = await rpc.request("session/prompt", { sessionId: acpSid, prompt: [{ type: "text", text }] });
        for (const id of openText) emit({ type: "text-end", id });
        for (const id of openReasoning) emit({ type: "reasoning-end", id });
        const finishReason = { unified: res.stopReason === "cancelled" ? "other" : "stop", raw: res.stopReason };
        const usage = mapUsage(res.usage);
        emit({ type: "finish-step", finishReason, usage });
        emit({ type: "finish", finishReason, totalUsage: usage });
      } catch (e) {
        for (const id of openText) { try { emit({ type: "text-end", id }); } catch {} }
        for (const id of openReasoning) { try { emit({ type: "reasoning-end", id }); } catch {} }
        emit({ type: "error", error: e });
        const finishReason = { unified: "other", raw: "error" };
        emit({ type: "finish-step", finishReason, usage: mapUsage({}) });
        emit({ type: "finish", finishReason, totalUsage: mapUsage({}) });
      }
      finally { currentEmit = null; }
    })();
    if (abortSignal) abortSignal.addEventListener("abort", () => {
      rpc.notify("session/cancel", { sessionId: acpSid });
    }, { once: true });
    return { submitToolResult: async () => {}, done: turn };
  }

  return {
    sessionId: startOpts.sessionId,
    isResume: instructionsApplied,
    modelId: settings.model ?? ns.models?.currentModelId,
    doPromptTurn: async (opts) => {
      let text = extractUserText(opts.prompt);
      if (!instructionsApplied && opts.instructions) text = opts.instructions + "\n\n" + text;
      instructionsApplied = true;
      return runTurn({ text, emit: opts.emit, abortSignal: opts.abortSignal });
    },
    doContinueTurn: async (opts) => runTurn({ text: "", emit: opts.emit, abortSignal: opts.abortSignal }),
    doCompact: async () => { throw new HarnessCapabilityUnsupportedError({ message: "mimo: no manual compaction", harnessId: "mimo" }); },
    doSuspendTurn: async () => { rpc.notify("session/cancel", { sessionId: acpSid }); return { type: "continue-turn", harnessId: "mimo", specificationVersion: "harness-v1", data: { acpSid } }; },
    doDetach: async () => ({ type: "resume-session", harnessId: "mimo", specificationVersion: "harness-v1", data: { acpSid } }),
    doStop: async () => { try { child.kill(); } catch {} return { type: "resume-session", harnessId: "mimo", specificationVersion: "harness-v1", data: { acpSid } }; },
    doDestroy: async () => { try { child.kill(); } catch {} },
  };
}

// ── host-fs HarnessV1SandboxProvider rooted at the task cwd ──────────────────
// MiMo runs its own tools against --cwd; this provider only needs to be a real
// dir the framework can mkdir <root>/mimo-<sessionId> under + satisfy the type.
function createHostFsSandbox(root) {
  const sh = (command, opts = {}) => new Promise((resolve) => {
    const c = spawn("bash", ["-lc", command], { cwd: opts.workingDirectory || root });
    let out = "", err = "";
    c.stdout.on("data", (d) => (out += d)); c.stderr.on("data", (d) => (err += d));
    c.on("close", (code) => resolve({ exitCode: code ?? 0, stdout: out, stderr: err }));
  });
  const abs = (p) => (p.startsWith("/") ? p : join(root, p));
  const base = {
    description: `host-fs sandbox rooted at ${root}`,
    run: sh,
    spawn: async (o) => {
      const c = spawn("bash", ["-lc", o.command], { cwd: o.workingDirectory || root });
      return { pid: c.pid, stdout: Readable.toWeb(c.stdout), stderr: Readable.toWeb(c.stderr),
        wait: () => new Promise((res) => c.on("close", (code) => res({ exitCode: code ?? 0 }))),
        kill: async () => { try { c.kill(); } catch {} } };
    },
    readTextFile: async (o) => { try { return await fsp.readFile(abs(o.path), o.encoding ?? "utf8"); } catch { return null; } },
    readBinaryFile: async (o) => { try { return new Uint8Array(await fsp.readFile(abs(o.path))); } catch { return null; } },
    readFile: async (o) => { try { return Readable.toWeb(createReadStream(abs(o.path))); } catch { return null; } },
    writeTextFile: async (o) => { await fsp.mkdir(dirname(abs(o.path)), { recursive: true }); await fsp.writeFile(abs(o.path), o.content, o.encoding ?? "utf8"); },
    writeBinaryFile: async (o) => { await fsp.mkdir(dirname(abs(o.path)), { recursive: true }); await fsp.writeFile(abs(o.path), o.content); },
    writeFile: async (o) => { await fsp.mkdir(dirname(abs(o.path)), { recursive: true }); const buf = []; for await (const ch of o.content) buf.push(Buffer.from(ch)); await fsp.writeFile(abs(o.path), Buffer.concat(buf)); },
  };
  return {
    specificationVersion: "harness-sandbox-v1",
    providerId: "host-fs",
    createSession: async () => ({
      ...base, id: root, defaultWorkingDirectory: root, ports: [],
      getPortUrl: async () => { throw new Error("no bridge ports"); },
      stop: async () => {}, restricted: () => base,
    }),
  };
}

// ── outer ACP server (benchflow <-> this process) ───────────────────────────
async function ensureSession() {
  if (harnessSession) return cachedAgent;
  // Usage-off path: MiMo gets the gateway creds (OPENAI_*) + the bare model id.
  // The free mimo/mimo-auto channel needs no creds (this package's validated
  // path). The flagship xiaomi/* native route (a mimocode.json credential file +
  // provider/model ids) belongs to the benchflow-core `mimo` agent — this
  // package wires only OPENAI_*, not a mimocode.json.
  const env = {};
  const base = process.env.OPENAI_BASE_URL || process.env.OPENROUTER_BASE_URL;
  const key = process.env.OPENAI_API_KEY || process.env.OPENROUTER_API_KEY;
  if (base) env.OPENAI_BASE_URL = base;
  if (key) env.OPENAI_API_KEY = key;
  log(`init: model=${modelId} base=${base || "(default)"} keylen=${(key || "").length}`);
  const harness = createMimo({ model: modelId || undefined, env });
  cachedAgent = new HarnessAgent({ harness, sandbox: createHostFsSandbox(agentCwd) });
  harnessSession = await cachedAgent.createSession();
  sessionDir = join(agentCwd, `mimo-${harnessSession.sessionId}`);
  mkdirSync(sessionDir, { recursive: true });
  log("session dir:", sessionDir);
  seedIntoSession();
  return cachedAgent;
}

const KIND = { write: "write", read: "read", bash: "bash", edit: "write", ls: "read", grep: "search" };
const kindOf = (n) => KIND[(n || "").toLowerCase()] ?? "other";

async function runPrompt(text) {
  const abort = new AbortController();
  currentAbort = abort;
  let usage = null;
  try {
    const agent = await ensureSession();
    const result = await agent.stream({ session: harnessSession, prompt: text, abortSignal: abort.signal });
    for await (const part of result.fullStream) {
      switch (part.type) {
        case "text-delta": notify({ sessionUpdate: "agent_message_chunk", content: { type: "text", text: part.text } }); break;
        case "reasoning-delta": notify({ sessionUpdate: "agent_thought_chunk", content: { type: "text", text: part.text } }); break;
        case "tool-call": notify({ sessionUpdate: "tool_call", toolCallId: part.toolCallId,
          title: `${part.toolName} ${JSON.stringify(part.input ?? {}).slice(0, TITLE_MAX)}`, kind: kindOf(part.toolName) }); break;
        case "tool-result": notify({ sessionUpdate: "tool_call_update", toolCallId: part.toolCallId, status: "completed",
          content: [{ type: "content", content: { type: "text", text: String(part.output ?? part.result ?? "").slice(0, RESULT_MAX) } }] }); break;
        case "tool-error": notify({ sessionUpdate: "tool_call_update", toolCallId: part.toolCallId, status: "failed",
          content: [{ type: "content", content: { type: "text", text: "[tool-error] " + String(part.error).slice(0, RESULT_MAX) } }] }); break;
        case "finish": usage = part.totalUsage ?? null; break;
        case "error": notify({ sessionUpdate: "agent_thought", text: "[harness error] " + String(part.error) }); break;
      }
    }
  } catch (e) { log("runPrompt:", String(e)); notify({ sessionUpdate: "agent_thought", text: "[harness error] " + String(e) }); }
  if (sessionDir) syncBackToCwd();
  currentAbort = null;
  const u = usage || {};
  const it = u.inputTokens?.total ?? u.inputTokens, ot = u.outputTokens?.total ?? u.outputTokens;
  return { stopReason: abort.signal.aborted ? "cancelled" : "end_turn",
    usage: (it != null || ot != null)
      ? { inputTokens: it ?? 0, outputTokens: ot ?? 0, totalTokens: (it ?? 0) + (ot ?? 0) } : undefined };
}

async function handle(msg) {
  const { id, method, params = {} } = msg;
  try {
    if (method === "initialize")
      send({ jsonrpc: "2.0", id, result: { protocolVersion: 1, agentInfo: { name: "ai-sdk-harness-mimo", version: "1.0" },
        agentCapabilities: { loadSession: false, promptCapabilities: { image: false, audio: false } } } });
    else if (method === "session/new") { agentCwd = params.cwd || process.cwd(); send({ jsonrpc: "2.0", id, result: { sessionId } }); }
    else if (method === "session/set_model") { modelId = params.modelId || modelId; log("set_model:", modelId); send({ jsonrpc: "2.0", id, result: {} }); }
    else if (method === "session/prompt") {
      const text = (params.prompt || []).filter((p) => p && p.type === "text").map((p) => p.text || "").join("");
      send({ jsonrpc: "2.0", id, result: await runPrompt(text) });
    } else if (method === "session/cancel") { if (currentAbort) currentAbort.abort(); }
    else if (id != null) send({ jsonrpc: "2.0", id, result: {} });
  } catch (e) { if (id != null) send({ jsonrpc: "2.0", id, error: { code: -32603, message: String(e) } }); else log("dispatch:", String(e)); }
}

const rl = createInterface({ input: process.stdin });
log("ready; cwd=" + process.cwd());
rl.on("line", (line) => { const s = line.trim(); if (!s) return; let m; try { m = JSON.parse(s); } catch { return; } void handle(m); });
rl.on("close", () => log("stdin closed"));
