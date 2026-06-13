// acp_capture.mjs — drive an agent's ACP server through one prompt against the
// capturing mock upstream, and record what the model received + what the agent did.
// Use for the STANDALONE half of a parity check; run the same agent inside
// BenchFlow with the gateway pointed at this mock for the INSIDE half, then diff
// the two upstream-request logs with parity_diff.py.
//
//   node acp_capture.mjs --server <server.mjs> --out /tmp/outside.jsonl \
//        [--port 11500] [--model deepseek-v4-flash] [--cwd <dir>] [--prompt "..."]
import { spawn } from "node:child_process";
import { mkdtempSync, existsSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const arg = (k, d) => { const i = process.argv.indexOf(`--${k}`); return i > 0 ? process.argv[i + 1] : d; };
const HERE = dirname(fileURLToPath(import.meta.url));
const server = arg("server");
if (!server) { console.error("usage: --server <server.mjs> --out <log> [--port --model --cwd --prompt]"); process.exit(2); }
const out = arg("out", "/tmp/parity-outside.jsonl");
const port = Number(arg("port", "11500"));
const model = arg("model", "mock-model");
const cwd = arg("cwd", mkdtempSync(join(tmpdir(), "parity-")));
const prompt = arg("prompt", "Create a file named hello.txt in the current directory containing exactly: Hello, world!");

const mock = spawn(process.execPath, [join(HERE, "mock_upstream.mjs")],
  { env: { ...process.env, PORT: String(port), REQ_LOG: out, MOCK_TAG: "capture" }, stdio: ["ignore", "inherit", "inherit"] });
await new Promise((r) => setTimeout(r, 600));

const baseUrl = `http://127.0.0.1:${port}/v1`;
const agent = spawn(process.execPath, [server], {
  cwd,
  env: { ...process.env, OPENAI_BASE_URL: baseUrl, OPENAI_API_KEY: "mock-key",
         OPENROUTER_BASE_URL: baseUrl, OPENROUTER_API_KEY: "mock-key",
         BENCHFLOW_PROVIDER_MODEL: model },
  stdio: ["pipe", "pipe", "inherit"],
});
let buf = ""; const updates = []; const pending = new Map();
agent.stdout.on("data", (d) => { buf += d.toString(); let i;
  while ((i = buf.indexOf("\n")) >= 0) { const l = buf.slice(0, i).trim(); buf = buf.slice(i + 1); if (!l) continue;
    const m = JSON.parse(l); if (m.method === "session/update") updates.push(m.params.update);
    else if (m.id != null && pending.has(m.id)) pending.get(m.id)(m); } });
const rpc = (id, method, params) => new Promise((res) => { pending.set(id, res); agent.stdin.write(JSON.stringify({ jsonrpc: "2.0", id, method, params }) + "\n"); });

await rpc(1, "initialize", { protocolVersion: 1 });
await rpc(2, "session/new", { cwd });
await rpc(3, "session/set_model", { modelId: model });
const r = await rpc(4, "session/prompt", { prompt: [{ type: "text", text: prompt }] });
agent.stdin.end(); mock.kill();

const hello = join(cwd, "hello.txt");
console.log(JSON.stringify({
  upstreamLog: out,
  stopReason: r.result?.stopReason,
  toolCalls: updates.filter((u) => u.sessionUpdate === "tool_call").map((u) => u.title),
  fileWritten: existsSync(hello) ? readFileSync(hello, "utf8") : null,
}, null, 2));
process.exit(0);
