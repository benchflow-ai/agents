#!/usr/bin/env node
// Mock `mimo acp` that DIES mid-turn — simulates the 2GB-sandbox OOM-kill that
// took down the real inner child ~58s into citation-check. Speaks just enough
// inner ACP for server.mjs's createMimoSession to drive a turn, then exits
// without replying to session/prompt. Used by the inner-child-death regression.
import { createInterface } from "node:readline";
const send = (m) => process.stdout.write(JSON.stringify(m) + "\n");
const rl = createInterface({ input: process.stdin });
rl.on("line", (line) => {
  let m;
  try { m = JSON.parse(line.trim()); } catch { return; }
  if (m.method === "initialize")
    send({ jsonrpc: "2.0", id: m.id, result: { protocolVersion: 1, agentCapabilities: {} } });
  else if (m.method === "session/new")
    send({ jsonrpc: "2.0", id: m.id, result: { sessionId: "mock-sid-1", models: { currentModelId: "mimo/mimo-auto" } } });
  else if (m.method === "session/set_model")
    send({ jsonrpc: "2.0", id: m.id, result: {} });
  else if (m.method === "session/prompt") {
    // begin a turn (one tool_call update), then DIE without ever replying to the
    // prompt request — exactly the failure server.mjs must survive.
    send({ jsonrpc: "2.0", method: "session/update", params: { sessionId: "mock-sid-1",
      update: { sessionUpdate: "tool_call", toolCallId: "t1", title: "read test.bib", rawInput: {} } } });
    setTimeout(() => process.exit(137), 200); // 137 == OOM/SIGKILL exit code
  }
});
