// acp_smoke.mjs — generic ACP *routing* smoke-test for any agent launch command.
// Spawns `sh -c "<launch>"` as an ACP-over-stdio server with every common provider
// base-url/key/model env var pointed at the deterministic mock upstream, drives one
// real ACP turn as a minimal-but-correct client (advertises fs capabilities, threads
// the sessionId, auto-grants permissions and answers fs callbacks), and reports how
// many upstream chat/completions requests the agent emitted. >=1 == routes through the
// gateway. Hermetic: the mock IS the upstream (no live model / secret).
//   node acp_smoke.mjs --launch "<shell cmd>" [--model m] [--port N] [--cwd D] [--set-model]
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const arg = (k, d) => { const i = process.argv.indexOf(`--${k}`); return i > 0 ? process.argv[i + 1] : d; };
const has = (k) => process.argv.includes(`--${k}`);
const HERE = dirname(fileURLToPath(import.meta.url));
const launch = arg("launch"); if (!launch) { console.error("usage: --launch <cmd>"); process.exit(2); }
const port = Number(arg("port", "11700")); const model = arg("model", "deepseek-v4-flash");
const cwd = arg("cwd", mkdtempSync(join(tmpdir(), "smoke-"))); const out = join(cwd, "upstream.jsonl");
const base = `http://127.0.0.1:${port}/v1`;
const mock = spawn(process.execPath, [join(HERE, "mock_upstream.mjs")],
  { env: { ...process.env, PORT: String(port), REQ_LOG: out, MOCK_TAG: "smoke", MOCK_CWD: cwd }, stdio: ["ignore", "inherit", "inherit"] });
await new Promise((r) => setTimeout(r, 700));
const penv = { ...process.env,
  OPENAI_BASE_URL: base, OPENAI_API_BASE: base, OPENAI_API_KEY: "mock-key", OPENAI_MODEL: model,
  OPENROUTER_BASE_URL: base, OPENROUTER_API_KEY: "mock-key", ANTHROPIC_BASE_URL: base, ANTHROPIC_API_KEY: "mock-key",
  "OPENAI__BASE_URL": base, "OPENAI__API_KEY": "mock-key", GOOSE_PROVIDER: "openai", OPENAI_HOST: base,
  OPENAI_BASE_PATH: "v1/chat/completions", GOOSE_MODEL: model, BENCHFLOW_PROVIDER_BASE_URL: base,
  BENCHFLOW_PROVIDER_API_KEY: "mock-key", BENCHFLOW_PROVIDER_MODEL: model, BENCHFLOW_LITELLM_MODEL_ALIAS: model };
const agent = spawn("sh", ["-c", launch], { cwd, env: penv, stdio: ["pipe", "pipe", "inherit"] });
let buf = ""; const pending = new Map();
const send = (m) => agent.stdin.write(JSON.stringify(m) + "\n");
const reply = (id, result) => send({ jsonrpc: "2.0", id, result });
agent.stdout.on("data", (d) => { buf += d.toString(); let i;
  while ((i = buf.indexOf("\n")) >= 0) { const l = buf.slice(0, i).trim(); buf = buf.slice(i + 1); if (!l) continue;
    let m; try { m = JSON.parse(l); } catch { continue; }
    if (m.method && m.id != null) {           // agent -> client REQUEST: answer permissively
      const meth = m.method;
      if (meth.includes("request_permission")) reply(m.id, { outcome: { outcome: "selected", optionId: (m.params?.options?.[0]?.optionId) || "allow" } });
      else if (meth.includes("read_text_file")) reply(m.id, { content: "" });
      else if (meth.includes("write_text_file")) reply(m.id, null);
      else reply(m.id, {});
    } else if (m.id != null && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  } });
const rpc = (id, method, params, ms = 25000) => new Promise((res) => {
  let done = false; pending.set(id, (m) => { done = true; res(m); });
  setTimeout(() => { if (!done) res({ timeout: true }); }, ms); send({ jsonrpc: "2.0", id, method, params }); });
const countReqs = () => { try { return readFileSync(out, "utf8").trim().split("\n").filter(Boolean).length; } catch { return 0; } };
const fin = (extra) => { try { agent.stdin.end(); } catch {} agent.kill(); mock.kill();
  console.log(JSON.stringify({ upstreamRequests: countReqs(), ...extra })); process.exit(0); };
setTimeout(() => fin({ note: "overall-timeout" }), 100000);
try {
  const init = await rpc(1, "initialize", { protocolVersion: 1, clientCapabilities: { fs: { readTextFile: true, writeTextFile: true } } });
  const sn = await rpc(2, "session/new", { cwd, mcpServers: [] });
  const sid = sn.result?.sessionId ?? sn.result?.session_id ?? "smoke-1";
  if (has("set-model")) await rpc(3, "session/set_model", { sessionId: sid, modelId: model });
  const r = await rpc(4, "session/prompt", { sessionId: sid, prompt: [{ type: "text", text: "Create a file hello.txt with exactly: Hello, world!" }] }, 70000);
  fin({ initOk: !init.timeout, sessionId: sid, stopReason: r.result?.stopReason ?? null, promptTimeout: !!r.timeout });
} catch (e) { fin({ error: String(e) }); }
