// ACP-over-stdio server wrapping the AI SDK 7 HarnessAgent
// (DeepAgents harness + just-bash local sandbox). Routes the model through benchflow's
// gateway (OPENROUTER_* slot = OpenAI-compatible chat-completions) so the harness
// runs natively inside benchflow's task sandbox on the real task files.
//
// The harness composes a per-session working dir <root>/pi-<sessionId>; benchflow's
// task files + verifier live in the task cwd. So we BRIDGE: pre-seed the task files
// into the session dir before the turn, and sync the agent's results back to the
// task cwd after — so the agent operates on the real task and the verifier sees it.
import { createInterface } from "node:readline";
import { cpSync, readdirSync, mkdirSync, symlinkSync, existsSync } from "node:fs";
import { join, basename } from "node:path";
import { HarnessAgent } from "@ai-sdk/harness/agent";
import { createDeepAgents } from "@ai-sdk/harness-deepagents";
import { createJustBashSandbox } from "@ai-sdk/sandbox-just-bash";
import { Sandbox, ReadWriteFs } from "just-bash";

for (const k of ["HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy",
                 "NO_PROXY", "no_proxy", "NODE_TLS_REJECT_UNAUTHORIZED"]) delete process.env[k];

const log = (...a) => process.stderr.write("[ai-sdk-deepagents] " + a.join(" ") + "\n");
const RESULT_MAX = 2000, TITLE_MAX = 800;
function send(m) { process.stdout.write(JSON.stringify(m) + "\n"); }
function notify(u) { send({ jsonrpc: "2.0", method: "session/update", params: { sessionId, update: u } }); }

let sessionId = "ai-sdk-deepagents-1";
let agentCwd = process.cwd();
let modelId = process.env.BENCHFLOW_PROVIDER_MODEL || "";
let harnessSession = null, sessionDir = null, currentAbort = null, cachedAgent = null;

const isPiDir = (n) => /^pi-/.test(n);
const seedIntoSession = () => {                       // task files -> session dir
  for (const e of readdirSync(agentCwd, { withFileTypes: true })) {
    if (isPiDir(e.name) || e.isSymbolicLink()) continue;  // skip pi dirs + the abs-path symlink (itself a symlink)
    cpSync(join(agentCwd, e.name), join(sessionDir, e.name), { recursive: true });
  }
};
const syncBackToCwd = () => {                          // agent results -> task cwd
  try {
    for (const e of readdirSync(sessionDir, { withFileTypes: true }))
      cpSync(join(sessionDir, e.name), join(agentCwd, e.name), { recursive: true });
  } catch (e) { log("sync-back error:", String(e)); }
};

async function ensureSession() {
  if (harnessSession) return cachedAgent;
  let base = process.env.OPENROUTER_BASE_URL || process.env.OPENAI_BASE_URL || "";
  if (base && !/\/v\d+\/?$/.test(base)) base = base.replace(/\/+$/, "") + "/v1";  // pi posts {base}/chat/completions
  const key = process.env.OPENROUTER_API_KEY || process.env.OPENAI_API_KEY || "";
  log(`init: model=${modelId} base=${base} keylen=${key.length}`);  // stderr only — never into the trajectory
  const harness = createDeepAgents({ auth: { customEnv: { OPENROUTER_API_KEY: key, OPENROUTER_BASE_URL: base } }, model: modelId });
  const sb = await Sandbox.create({ fs: new ReadWriteFs({ root: agentCwd, allowSymlinks: true }), cwd: "/" });
  cachedAgent = new HarnessAgent({ harness, sandbox: createJustBashSandbox({ sandbox: sb }) });
  harnessSession = await cachedAgent.createSession();
  sessionDir = join(agentCwd, `pi-${harnessSession.sessionId}`);
  mkdirSync(sessionDir, { recursive: true });
  // Make sandbox-absolute "<cwd>" (e.g. /app, where the verifier checks) resolve to
  // the REAL task dir: since ReadWriteFs root == agentCwd, sandbox "/app" == real
  // <agentCwd>/app, so symlink <agentCwd>/app -> <agentCwd>. Covers tasks that write
  // absolute /app paths; relative paths still land in the session dir + sync back.
  try {
    const link = join(agentCwd, basename(agentCwd));
    if (!existsSync(link)) symlinkSync(agentCwd, link);
  } catch (e) { log("abs-link:", String(e)); }
  log("session dir:", sessionDir);
  seedIntoSession();
  return cachedAgent;
}

const KIND = { write: "write", read: "read", bash: "bash", edit: "write", ls: "read", grep: "search" };
const kindOf = (n) => KIND[n] ?? "other";

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
          content: [{ type: "content", content: { type: "text", text: String(part.output ?? "").slice(0, RESULT_MAX) } }] }); break;
        case "tool-error": notify({ sessionUpdate: "tool_call_update", toolCallId: part.toolCallId, status: "failed",
          content: [{ type: "content", content: { type: "text", text: "[tool-error] " + String(part.error).slice(0, RESULT_MAX) } }] }); break;
        case "finish": usage = part.totalUsage ?? null; break;
        case "error": notify({ sessionUpdate: "agent_thought", text: "[harness error] " + String(part.error) }); break;
      }
    }
  } catch (e) { log("runPrompt:", String(e)); notify({ sessionUpdate: "agent_thought", text: "[harness error] " + String(e) }); }
  if (sessionDir) syncBackToCwd();                     // make results visible to the verifier
  currentAbort = null;
  const u = usage || {};
  return { stopReason: abort.signal.aborted ? "cancelled" : "end_turn",
    usage: (u.inputTokens != null || u.outputTokens != null)
      ? { inputTokens: u.inputTokens ?? 0, outputTokens: u.outputTokens ?? 0, totalTokens: u.totalTokens ?? 0 } : undefined };
}

async function handle(msg) {
  const { id, method, params = {} } = msg;
  try {
    if (method === "initialize")
      send({ jsonrpc: "2.0", id, result: { protocolVersion: 1, agentInfo: { name: "ai-sdk-deepagents", version: "1.0" },
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
