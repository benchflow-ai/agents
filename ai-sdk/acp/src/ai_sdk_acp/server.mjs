// server.mjs — pure-JS ACP-over-stdio server wrapping a Vercel AI SDK ToolLoopAgent.
// Hardened for inside==outside behavioral parity (see PARITY FIXES below).
// Framing: newline-delimited JSON-RPC 2.0. STDOUT = protocol ONLY; STDERR = all logs.
import { createInterface } from "node:readline";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { writeFile as fsWrite, readFile as fsRead, mkdir } from "node:fs/promises";
import { dirname, resolve, isAbsolute } from "node:path";
import { ToolLoopAgent, stepCountIs, tool } from "ai";
import { createOpenAICompatible } from "@ai-sdk/openai-compatible";
import { z } from "zod";

// ── PARITY FIX (env): neutralize latent, environment-inherited vars that would
// make outbound model HTTP / TLS differ between the sandbox and a standalone host.
// (NODE_OPTIONS is applied at node startup, so it is stripped in launch_cmd, not here.)
for (const k of ["HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy",
                 "NO_PROXY", "no_proxy", "NODE_TLS_REJECT_UNAUTHORIZED"]) {
  delete process.env[k];
}

const PROTOCOL_VERSION = 1;
const HEARTBEAT_MS = Number(process.env.BF_HEARTBEAT_MS || 10000);
const TITLE_MAX = 800;   // tool_call title (name + args) truncation
const RESULT_MAX = 2000; // tool_call_update content (result / error) truncation
const log = (...a) => process.stderr.write("[ai-sdk] " + a.join(" ") + "\n");
const pexec = promisify(execFile);

function send(msg) { process.stdout.write(JSON.stringify(msg) + "\n"); }
function notify(update) {
  send({ jsonrpc: "2.0", method: "session/update", params: { sessionId, update } });
}

let sessionId = "ai-sdk-1";
let modelId = process.env.BENCHFLOW_PROVIDER_MODEL || "";
let agentCwd = process.cwd();
let currentAbort = null;

const inCwd = (p) => (isAbsolute(p) ? p : resolve(agentCwd, p));

// ── PARITY FIX (watchdog): while a tool executes (potentially for minutes with no
// model output), emit a periodic tool_call_update so benchflow's idle watchdog is
// fed and does not cancel a working agent that a standalone run (no watchdog) would
// let finish. The model never sees these; they only keep the ACP channel alive.
function withHeartbeat(toolCallId, fn) {
  const iv = setInterval(() => {
    try { notify({ sessionUpdate: "tool_call_update", toolCallId, status: "in_progress" }); } catch {}
  }, HEARTBEAT_MS);
  if (iv.unref) iv.unref();
  return Promise.resolve()
    .then(fn)
    .finally(() => clearInterval(iv));
}

const tools = {
  bash: tool({
    description: "Run a bash command in the workspace and return combined stdout/stderr.",
    inputSchema: z.object({ command: z.string().describe("the shell command") }),
    execute: async ({ command }, { toolCallId, abortSignal }) =>
      withHeartbeat(toolCallId, async () => {
        // signal: a session/cancel aborts the AI SDK loop AND kills the in-flight child.
        const r = await pexec("bash", ["-lc", command], { cwd: agentCwd, maxBuffer: 8 << 20, signal: abortSignal })
          .catch((e) => ({ stdout: e.stdout || "", stderr: (e.stderr || "") + "\n" + String(e) }));
        return (r.stdout || "") + (r.stderr ? "\n[stderr]\n" + r.stderr : "") || "(no output)";
      }),
  }),
  writeFile: tool({
    description: "Write text to a file (creating parent dirs). Overwrites if it exists.",
    inputSchema: z.object({ path: z.string(), content: z.string() }),
    execute: async ({ path, content }, { toolCallId }) =>
      withHeartbeat(toolCallId, async () => {
        const abs = inCwd(path);
        await mkdir(dirname(abs), { recursive: true }).catch(() => {});
        await fsWrite(abs, content);
        return `wrote ${content.length} bytes to ${abs}`;
      }),
  }),
  readFile: tool({
    description: "Read a UTF-8 text file.",
    inputSchema: z.object({ path: z.string() }),
    execute: async ({ path }, { toolCallId }) =>
      withHeartbeat(toolCallId, async () => {
        try { return await fsRead(inCwd(path), "utf8"); }
        catch (e) { return "[read error] " + String(e); }
      }),
  }),
};

const KIND = { bash: "bash", readFile: "read", writeFile: "write" };
const kindOf = (name) => KIND[name] ?? "other";

function makeModel(id) {
  const provider = createOpenAICompatible({
    name: "benchflow-gateway",
    baseURL: process.env.OPENAI_BASE_URL,
    apiKey: process.env.OPENAI_API_KEY,
    includeUsage: true,
  });
  return provider.chatModel(id);
}

async function runPrompt(text) {
  const abort = new AbortController();
  currentAbort = abort;
  const agent = new ToolLoopAgent({
    model: makeModel(modelId),
    // ── PARITY FIX (cwd): do NOT embed the absolute working directory in the system
    // prompt — that made the model-facing text differ (/app vs a local dir) between
    // environments. The agent still operates in agentCwd; paths are resolved there.
    instructions:
      "You are an autonomous coding agent. Use the tools (bash, writeFile, readFile) " +
      "to complete the user's task fully. Paths are relative to your current working " +
      "directory unless absolute. Do exactly what is asked. When complete, stop.",
    tools,
    stopWhen: stepCountIs(40),
  });

  let totalUsage = null;
  try {
    const result = await agent.stream({ prompt: text, abortSignal: abort.signal });
    for await (const part of result.fullStream) {
      switch (part.type) {
        case "text-delta":
          notify({ sessionUpdate: "agent_message_chunk", content: { type: "text", text: part.text } });
          break;
        case "reasoning-delta":
          notify({ sessionUpdate: "agent_thought_chunk", content: { type: "text", text: part.text } });
          break;
        case "tool-call":
          notify({
            sessionUpdate: "tool_call",
            toolCallId: part.toolCallId,
            title: `${part.toolName} ${JSON.stringify(part.input ?? {}).slice(0, TITLE_MAX)}`,
            kind: kindOf(part.toolName),
          });
          break;
        case "tool-result":
          notify({
            sessionUpdate: "tool_call_update",
            toolCallId: part.toolCallId,
            status: "completed",
            content: [{ type: "content", content: { type: "text", text: String(part.output ?? "").slice(0, RESULT_MAX) } }],
          });
          break;
        case "tool-error":
          notify({
            sessionUpdate: "tool_call_update",
            toolCallId: part.toolCallId,
            status: "failed",
            content: [{ type: "content", content: { type: "text", text: "[tool-error] " + String(part.error).slice(0, RESULT_MAX) } }],
          });
          break;
        case "finish":
          totalUsage = part.totalUsage ?? null;
          break;
        case "error":
          notify({ sessionUpdate: "agent_thought", text: "[ai-sdk stream error] " + String(part.error) });
          break;
      }
    }
  } catch (e) {
    log("runPrompt error:", String(e));
    notify({ sessionUpdate: "agent_thought", text: "[ai-sdk error] " + String(e) });
  }
  currentAbort = null;
  const u = totalUsage || {};
  return {
    stopReason: abort.signal.aborted ? "cancelled" : "end_turn",
    usage: (u.inputTokens != null || u.outputTokens != null) ? {
      inputTokens: u.inputTokens ?? 0,
      outputTokens: u.outputTokens ?? 0,
      totalTokens: u.totalTokens ?? ((u.inputTokens ?? 0) + (u.outputTokens ?? 0)),
    } : undefined,
  };
}

async function handleMessage(msg) {
  const { id, method, params = {} } = msg;
  try {
    if (method === "initialize") {
      send({ jsonrpc: "2.0", id, result: {
        protocolVersion: PROTOCOL_VERSION,
        agentInfo: { name: "ai-sdk", version: "1.0" },
        agentCapabilities: { loadSession: false, promptCapabilities: { image: false, audio: false } },
      }});
    } else if (method === "session/new") {
      agentCwd = params.cwd || process.cwd();
      sessionId = "ai-sdk-1";
      send({ jsonrpc: "2.0", id, result: { sessionId } });
    } else if (method === "session/set_model") {
      modelId = params.modelId || modelId;
      log("set_model:", modelId);
      send({ jsonrpc: "2.0", id, result: {} });
    } else if (method === "session/prompt") {
      const text = (params.prompt || []).filter((p) => p && p.type === "text").map((p) => p.text || "").join("");
      const out = await runPrompt(text);
      send({ jsonrpc: "2.0", id, result: out });
    } else if (method === "session/cancel") {
      // NOTIFICATION (no id, no reply). Delivered via the line event WHILE a prompt
      // is in flight, so it can actually abort the running ToolLoopAgent stream.
      if (currentAbort) currentAbort.abort();
    } else if (id != null) {
      send({ jsonrpc: "2.0", id, result: {} });
    }
  } catch (e) {
    if (id != null) send({ jsonrpc: "2.0", id, error: { code: -32603, message: String(e) } });
    else log("dispatch error", method, String(e));
  }
}

// Event-based dispatch (NOT `for await` over the iterator): a `for await` loop is
// blocked on the in-flight prompt's await and would not read the next stdin line —
// so session/cancel would sit unread until the prompt already finished. With the
// line event, cancel is delivered mid-prompt and aborts the run.
const rl = createInterface({ input: process.stdin });
log("ready; cwd=" + process.cwd() + " heartbeat=" + HEARTBEAT_MS + "ms");
rl.on("line", (line) => {
  const s = line.trim();
  if (!s) return;
  let msg;
  try { msg = JSON.parse(s); } catch { return; }
  void handleMessage(msg);
});
rl.on("close", () => { log("stdin closed; exiting"); });
