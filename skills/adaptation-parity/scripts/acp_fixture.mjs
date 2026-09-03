import readline from "node:readline";
import { spawn } from "node:child_process";
import { writeFileSync } from "node:fs";
import { join } from "node:path";

const mode = process.env.ACP_FIXTURE_MODE ?? "ok";
if (process.env.ACP_FIXTURE_HOME_MARKER)
  writeFileSync(
    join(process.env.HOME, process.env.ACP_FIXTURE_HOME_MARKER),
    "isolated",
  );
if (process.env.ACP_FIXTURE_CHILD_PID) {
  const child = spawn(process.execPath, ["-e", "setInterval(() => {}, 1000)"], {
    stdio: "ignore",
  });
  writeFileSync(process.env.ACP_FIXTURE_CHILD_PID, String(child.pid));
}

const send = (message) => process.stdout.write(`${JSON.stringify(message)}\n`);
const response = (id, result) => send({ jsonrpc: "2.0", id, result });
const pending = new Map();
let callbackId = 100;
let sessionId;

function call(method, params) {
  const id = callbackId++;
  send({ jsonrpc: "2.0", id, method, params });
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
}

async function postMock() {
  await fetch(`${process.env.BENCHFLOW_PROVIDER_BASE_URL}/chat/completions`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      model: process.env.BENCHFLOW_PROVIDER_MODEL,
      messages: [{ role: "user", content: "strict fixture" }],
      tools: [
        {
          type: "function",
          function: {
            name: "fixtureTool",
            parameters: { type: "object" },
          },
        },
      ],
      stream: true,
    }),
  });
}

const earlyPrompt = {
  exit: () => process.exit(7),
  malformed: () => process.stdout.write("not-json\n"),
  null: () => process.stdout.write("null\n"),
  primitive: () => process.stdout.write("42\n"),
  array: () => process.stdout.write("[]\n"),
  hang: () => undefined,
  "rpc-error": (message) =>
    send({
      jsonrpc: "2.0",
      id: message.id,
      error: { code: -32000, message: "fixture RPC rejection" },
    }),
};

async function prompt(message) {
  if (earlyPrompt[mode]) return earlyPrompt[mode](message);
  if (message.params?.sessionId !== sessionId)
    throw new Error("missing sessionId on prompt");
  const permission = await call("session/request_permission", {
    options: [{ optionId: "allow" }],
  });
  if (permission?.outcome?.optionId !== "allow")
    throw new Error("permission callback failed");

  const path =
    process.env.ACP_FIXTURE_PATH ?? join(process.cwd(), "callback.txt");
  try {
    await call("fs/write_text_file", { path, content: "callback-ok" });
  } catch (error) {
    return send({
      jsonrpc: "2.0",
      id: message.id,
      error: {
        code: -32001,
        message: `fs callback rejected: ${error.message}`,
      },
    });
  }
  const read = await call("fs/read_text_file", { path });
  if (read?.content !== "callback-ok") throw new Error("fs callback failed");

  const names = (key) => (process.env[key] ?? "").split(",").filter(Boolean);
  const leaked = names("EXPECT_SCRUBBED_ENV").filter(
    (name) => process.env[name] === "must-not-leak",
  );
  if (leaked.length) throw new Error("ambient provider config leaked");
  const removed = names("EXPECT_PRESERVED_ENV").filter(
    (name) => !process.env[name],
  );
  if (removed.length) throw new Error("unrelated environment was removed");
  if (mode !== "no-upstream") await postMock();
  response(message.id, { stopReason: "end_turn" });
}

const handlers = {
  initialize(message) {
    if (!message.params?.clientCapabilities?.fs?.readTextFile)
      throw new Error("missing fs capability");
    return response(message.id, { protocolVersion: 1 });
  },
  "session/new"(message) {
    if (!Array.isArray(message.params?.mcpServers))
      throw new Error("missing mcpServers");
    sessionId = "strict-session";
    return response(message.id, { sessionId });
  },
  "session/set_model"(message) {
    if (mode === "reject-set-model")
      return send({
        jsonrpc: "2.0",
        id: message.id,
        error: { code: -32601, message: "set_model unsupported" },
      });
    if (message.params?.sessionId !== sessionId)
      throw new Error("missing sessionId on set_model");
    return response(message.id, {});
  },
  "session/prompt": prompt,
};

async function handle(message) {
  if (message.id != null && !message.method && pending.has(message.id)) {
    const callback = pending.get(message.id);
    pending.delete(message.id);
    return message.error
      ? callback.reject(new Error(message.error.message))
      : callback.resolve(message.result);
  }
  return handlers[message.method]?.(message);
}

readline.createInterface({ input: process.stdin }).on("line", (line) => {
  void handle(JSON.parse(line)).catch((error) => {
    process.stderr.write(`${error.message}\n`);
    process.exit(8);
  });
});
