#!/usr/bin/env node
// Recording mock `mimo acp`: speaks enough inner ACP for server.mjs's
// createMimoSession to drive one turn, and writes the modelId it received via
// `session/set_model` to $MIMO_RECORD_FILE so a key-free test can assert the
// inner model became `benchflow/<alias>` in proxy mode. Completes the turn so
// the outer session/prompt resolves cleanly.
import { createInterface } from "node:readline";
import { writeFileSync } from "node:fs";
const send = (m) => process.stdout.write(JSON.stringify(m) + "\n");
const sid = "mock-record-1";
const recordFile = process.env.MIMO_RECORD_FILE;
const rl = createInterface({ input: process.stdin });
rl.on("line", (line) => {
  let m;
  try { m = JSON.parse(line.trim()); } catch { return; }
  if (m.method === "initialize")
    send({ jsonrpc: "2.0", id: m.id, result: { protocolVersion: 1, agentCapabilities: {} } });
  else if (m.method === "session/new")
    send({ jsonrpc: "2.0", id: m.id, result: { sessionId: sid, models: { currentModelId: "mimo/mimo-auto" } } });
  else if (m.method === "session/set_model") {
    if (recordFile) { try { writeFileSync(recordFile, String(m.params?.modelId ?? "")); } catch {} }
    send({ jsonrpc: "2.0", id: m.id, result: {} });
  } else if (m.method === "session/prompt") {
    send({ jsonrpc: "2.0", method: "session/update", params: { sessionId: sid,
      update: { sessionUpdate: "tool_call", toolCallId: "t1", title: "read test.bib", rawInput: {} } } });
    send({ jsonrpc: "2.0", method: "session/update", params: { sessionId: sid,
      update: { sessionUpdate: "tool_call_update", toolCallId: "t1", status: "completed", content: { type: "text", text: "ok" } } } });
    send({ jsonrpc: "2.0", id: m.id, result: { stopReason: "end_turn", usage: { inputTokens: 10, outputTokens: 5, totalTokens: 15 } } });
  }
});
