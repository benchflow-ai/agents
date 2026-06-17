#!/usr/bin/env node
// Healthy mock `mimo acp` whose shebang (`#!/usr/bin/env node`) needs `node` on
// PATH — used to prove server.mjs makes node findable for the launcher even when
// the sandbox PATH lacks it (else this launcher exits 127). Speaks enough inner
// ACP to complete one tool-using turn.
import { createInterface } from "node:readline";
const send = (m) => process.stdout.write(JSON.stringify(m) + "\n");
const sid = "mock-ok-1";
const rl = createInterface({ input: process.stdin });
rl.on("line", (line) => {
  let m;
  try { m = JSON.parse(line.trim()); } catch { return; }
  if (m.method === "initialize")
    send({ jsonrpc: "2.0", id: m.id, result: { protocolVersion: 1, agentCapabilities: {} } });
  else if (m.method === "session/new")
    send({ jsonrpc: "2.0", id: m.id, result: { sessionId: sid, models: { currentModelId: "mimo/mimo-auto" } } });
  else if (m.method === "session/set_model")
    send({ jsonrpc: "2.0", id: m.id, result: {} });
  else if (m.method === "session/prompt") {
    send({ jsonrpc: "2.0", method: "session/update", params: { sessionId: sid,
      update: { sessionUpdate: "tool_call", toolCallId: "t1", title: "read test.bib", rawInput: {} } } });
    send({ jsonrpc: "2.0", method: "session/update", params: { sessionId: sid,
      update: { sessionUpdate: "tool_call_update", toolCallId: "t1", status: "completed", content: { type: "text", text: "ok" } } } });
    send({ jsonrpc: "2.0", method: "session/update", params: { sessionId: sid,
      update: { sessionUpdate: "agent_message_chunk", content: { type: "text", text: "done" } } } });
    send({ jsonrpc: "2.0", id: m.id, result: { stopReason: "end_turn", usage: { inputTokens: 10, outputTokens: 5, totalTokens: 15 } } });
  }
});
