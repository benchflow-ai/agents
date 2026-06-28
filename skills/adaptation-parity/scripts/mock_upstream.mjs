// mock_upstream.mjs — deterministic, capturing OpenAI-compatible /chat/completions
// mock for parity checks. Logs every received request body to REQ_LOG (one JSON
// per line) and returns a fixed 2-turn SSE response (a writeFile tool call, then
// final text), so an agent's behavior is deterministic and its upstream requests
// can be diffed inside-BenchFlow vs standalone.
//
//   PORT=11500 REQ_LOG=/tmp/caps.jsonl MOCK_TAG=outside node mock_upstream.mjs
import http from "node:http";
import { appendFileSync } from "node:fs";

const PORT = Number(process.env.PORT || 11500);
const REQ_LOG = process.env.REQ_LOG || "/tmp/parity-upstream.jsonl";
const TAG = process.env.MOCK_TAG || "mock";
// The agent's OWN task cwd for this capture (standalone temp-dir, or /app inside
// BenchFlow). Recorded on every logged line so the parity normalizer collapses
// each side's cwd to <CWD> symmetrically. Empty when unset (older captures).
const MOCK_CWD = process.env.MOCK_CWD || "";
const RESP_ID = "chatcmpl-parity-0001";
const TOOL_ID = "call_parity_writeFile_0001";
const frame = (o) => `data: ${JSON.stringify(o)}\n\n`;
const base = { id: RESP_ID, created: 1700000000, model: "mock-model", object: "chat.completion.chunk" };

function toolCallChunks() {
  const out = [frame({ ...base, choices: [{ index: 0, delta: { role: "assistant", tool_calls: [
    { index: 0, id: TOOL_ID, type: "function", function: { name: "writeFile", arguments: "" } }] }, finish_reason: null }] })];
  for (const p of ['{"path":', '"hello.txt"', ',"content":', '"Hello, world!"', "}"])
    out.push(frame({ ...base, choices: [{ index: 0, delta: { tool_calls: [{ index: 0, function: { arguments: p } }] }, finish_reason: null }] }));
  out.push(frame({ ...base, choices: [{ index: 0, delta: {}, finish_reason: "tool_calls" }] }));
  return out;
}
function finalChunks() {
  return [
    frame({ ...base, choices: [{ index: 0, delta: { role: "assistant", content: "done" }, finish_reason: null }] }),
    frame({ ...base, choices: [{ index: 0, delta: {}, finish_reason: "stop" }] }),
  ];
}
const usageChunk = () => frame({ ...base, choices: [],
  usage: { prompt_tokens: 50, completion_tokens: 12, total_tokens: 62,
    prompt_tokens_details: { cached_tokens: 0 }, completion_tokens_details: { reasoning_tokens: 0 } } });

http.createServer((req, res) => {
  if (req.method !== "POST" || !req.url.endsWith("/chat/completions")) return res.writeHead(404).end();
  let raw = ""; req.on("data", (c) => (raw += c));
  req.on("end", () => {
    let body = {}; try { body = JSON.parse(raw); } catch {}
    const rec = { tag: TAG, body };
    if (MOCK_CWD) rec.cwd = MOCK_CWD;
    appendFileSync(REQ_LOG, JSON.stringify(rec) + "\n");
    const hasTool = (body.messages || []).some((m) => m && m.role === "tool");
    res.writeHead(200, { "Content-Type": "text/event-stream; charset=utf-8" });
    for (const c of (hasTool ? finalChunks() : toolCallChunks())) res.write(c);
    if (body.stream_options && body.stream_options.include_usage) res.write(usageChunk());
    res.write("data: [DONE]\n\n"); res.end();
  });
}).listen(PORT, "0.0.0.0", () => process.stderr.write(`[mock_upstream] :${PORT} log=${REQ_LOG} tag=${TAG}\n`));
