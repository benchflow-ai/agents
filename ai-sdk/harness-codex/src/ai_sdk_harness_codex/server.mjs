// EXPERIMENTAL — Vercel AI SDK 7 HarnessAgent (Codex harness) over ACP.
//
// ⚠️ DOES NOT RUN AS A BENCHFLOW EVAL. The Codex harness is bridge-backed: it
// requires a port-exposing Vercel sandbox (@ai-sdk/sandbox-vercel + Vercel creds),
// which is REMOTE — the agent's files land in the Vercel sandbox, not benchflow's
// task /app, so the verifier cannot see them. The local just-bash sandbox (used by
// ai-sdk/harness-pi) rejects bridge-backed harnesses. For real benchflow evaluation
// of Codex, use benchflow's native `codex-acp` agent. This package is shipped for
// completeness and as a template for a Vercel-sandbox HarnessAgent.
//
// Framing: newline-delimited JSON-RPC 2.0; STDOUT = protocol only, STDERR = logs.
import { createInterface } from "node:readline";
import { HarnessAgent } from "@ai-sdk/harness/agent";
import { createCodex } from "@ai-sdk/harness-codex";
import { createVercelSandbox } from "@ai-sdk/sandbox-vercel";

const log = (...a) => process.stderr.write("[ai-sdk-codex] " + a.join(" ") + "\n");
const RESULT_MAX = 2000, TITLE_MAX = 800;
function send(m) { process.stdout.write(JSON.stringify(m) + "\n"); }
function notify(u) { send({ jsonrpc: "2.0", method: "session/update", params: { sessionId, update: u } }); }

let sessionId = "ai-sdk-codex-1";
let modelId = process.env.BENCHFLOW_PROVIDER_MODEL || "";
let harnessSession = null, cachedAgent = null, currentAbort = null;

async function ensureSession() {
  if (harnessSession) return cachedAgent;
  const harness = createCodex({
    // Codex speaks the OpenAI Responses API; auth via OPENAI_API_KEY / AI Gateway.
    ...(modelId ? { model: modelId } : {}),
  });
  // Bridge-backed → MUST be a port-exposing sandbox. Vercel sandbox requires creds;
  // this is the line that cannot be satisfied by benchflow's local sandbox.
  const sandbox = createVercelSandbox({ runtime: "node24", ports: [4000] });
  cachedAgent = new HarnessAgent({ harness, sandbox });
  harnessSession = await cachedAgent.createSession();
  return cachedAgent;
}

const KIND = { write: "write", read: "read", bash: "bash", edit: "write", apply_patch: "write" };
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
      send({ jsonrpc: "2.0", id, result: { protocolVersion: 1, agentInfo: { name: "ai-sdk-codex", version: "1.0" },
        agentCapabilities: { loadSession: false, promptCapabilities: { image: false, audio: false } } } });
    else if (method === "session/new") send({ jsonrpc: "2.0", id, result: { sessionId } });
    else if (method === "session/set_model") { modelId = params.modelId || modelId; send({ jsonrpc: "2.0", id, result: {} }); }
    else if (method === "session/prompt") {
      const text = (params.prompt || []).filter((p) => p && p.type === "text").map((p) => p.text || "").join("");
      send({ jsonrpc: "2.0", id, result: await runPrompt(text) });
    } else if (method === "session/cancel") { if (currentAbort) currentAbort.abort(); }
    else if (id != null) send({ jsonrpc: "2.0", id, result: {} });
  } catch (e) { if (id != null) send({ jsonrpc: "2.0", id, error: { code: -32603, message: String(e) } }); else log("dispatch:", String(e)); }
}

const rl = createInterface({ input: process.stdin });
log("ready (EXPERIMENTAL: requires a Vercel sandbox; not a benchflow-local eval)");
rl.on("line", (line) => { const s = line.trim(); if (!s) return; let m; try { m = JSON.parse(s); } catch { return; } void handle(m); });
rl.on("close", () => log("stdin closed"));
