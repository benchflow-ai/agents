import { spawn } from "node:child_process";
import {
  existsSync,
  mkdtempSync,
  readFileSync,
  realpathSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { basename, dirname, join, relative, resolve, sep } from "node:path";
import { tmpdir } from "node:os";
import readline from "node:readline";

const PROVIDER_ENV = new Set(
  JSON.parse(readFileSync(new URL("./provider_env.json", import.meta.url))),
);

export function option(argv, name, fallback) {
  const index = argv.indexOf(`--${name}`);
  if (index < 0) return fallback;
  const value = argv[index + 1];
  if (!value || value.startsWith("--"))
    throw new Error(`--${name} requires a value`);
  return value;
}

export function positiveNumber(value, name, { integer = false, max } = {}) {
  const number = Number(value);
  if (!Number.isFinite(number) || number < 1)
    throw new Error(`--${name} must be positive`);
  if (integer && !Number.isInteger(number))
    throw new Error(`--${name} must be an integer`);
  if (max && number > max) throw new Error(`--${name} must be 1..${max}`);
  return number;
}

function agentEnv(baseUrl, model, home) {
  const clean = Object.fromEntries(
    Object.entries(process.env).filter(([name]) => !PROVIDER_ENV.has(name)),
  );
  for (const name of [
    "OPENAI_BASE_URL",
    "OPENAI_API_BASE",
    "OPENROUTER_BASE_URL",
    "OPENAI__BASE_URL",
    "OPENAI_HOST",
    "BENCHFLOW_PROVIDER_BASE_URL",
  ])
    clean[name] = baseUrl;
  for (const name of [
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "OPENAI__API_KEY",
    "BENCHFLOW_PROVIDER_API_KEY",
  ])
    clean[name] = "mock-key";
  for (const name of [
    "OPENAI_MODEL",
    "GOOSE_MODEL",
    "BENCHFLOW_PROVIDER_MODEL",
    "BENCHFLOW_LITELLM_MODEL_ALIAS",
  ])
    clean[name] = model;
  return Object.assign(clean, {
    HOME: home,
    XDG_CACHE_HOME: join(home, ".cache"),
    XDG_CONFIG_HOME: join(home, ".config"),
    XDG_DATA_HOME: join(home, ".local", "share"),
    OPENAI_BASE_PATH: "v1/chat/completions",
    GOOSE_PROVIDER: "openai",
    BENCHFLOW_PROVIDER_PROTOCOL: "openai-completions",
  });
}

function signalTree(child, signal) {
  if (!child?.pid) return;
  try {
    process.kill(process.platform === "win32" ? child.pid : -child.pid, signal);
  } catch (error) {
    if (error.code !== "ESRCH") throw error;
  }
}

async function stop(child) {
  if (!child) return;
  child.stdin?.end();
  signalTree(child, "SIGTERM");
  await Promise.race([
    new Promise((done) => child.once("exit", done)),
    new Promise((done) => setTimeout(done, 500)),
  ]);
  signalTree(child, "SIGKILL");
}

function waitForMock(mock, port, timeoutMs) {
  return new Promise((resolveReady, rejectReady) => {
    let tail = "";
    const finish = (error) => {
      clearTimeout(timer);
      mock.off("error", onError);
      mock.off("exit", onExit);
      mock.stderr.off("data", onData);
      error ? rejectReady(error) : resolveReady();
    };
    const onError = (error) =>
      finish(new Error(`mock spawn failed: ${error.message}`));
    const onExit = (code) =>
      finish(new Error(`mock exited before claiming port ${port} (${code})`));
    const onData = (chunk) => {
      process.stderr.write(chunk);
      tail = `${tail}${chunk}`.slice(-1000);
      if (tail.includes(`[mock_upstream] :${port} `)) finish();
    };
    const timer = setTimeout(
      () =>
        finish(
          new Error(`mock did not claim port ${port} within ${timeoutMs}ms`),
        ),
      timeoutMs,
    );
    mock.once("error", onError);
    mock.once("exit", onExit);
    mock.stderr.on("data", onData);
  });
}

function confinedPath(cwd, path, writing = false) {
  const root = realpathSync(cwd);
  const lexical = resolve(root, path);
  const target = existsSync(lexical)
    ? realpathSync(lexical)
    : writing
      ? join(realpathSync(dirname(lexical)), basename(lexical))
      : lexical;
  const rel = relative(root, target);
  if (rel === ".." || rel.startsWith(`..${sep}`))
    throw new Error(`ACP filesystem path escapes cwd: ${path}`);
  return target;
}

const CALLBACKS = {
  "session/request_permission": (params) => ({
    outcome: {
      outcome: "selected",
      optionId: params.options?.[0]?.optionId ?? "allow",
    },
  }),
  "fs/read_text_file": (params, cwd) => ({
    content: readFileSync(confinedPath(cwd, params.path), "utf8"),
  }),
  "fs/write_text_file": (params, cwd) => {
    writeFileSync(confinedPath(cwd, params.path, true), params.content, "utf8");
    return null;
  },
};

class AcpClient {
  constructor(agent, cwd, timeoutMs) {
    this.agent = agent;
    this.cwd = cwd;
    this.timeoutMs = timeoutMs;
    this.nextId = 1;
    this.pending = new Map();
    this.updates = [];
    this.failure = null;
    readline
      .createInterface({ input: agent.stdout })
      .on("line", (line) => this.onLine(line));
    agent.once("error", (error) =>
      this.fail(`agent spawn failed: ${error.message}`),
    );
    agent.stdin.on("error", (error) =>
      this.fail(`agent stdin failed: ${error.message}`),
    );
    agent.once("exit", (code, signal) => {
      if (this.pending.size)
        this.fail(`agent exited before ACP response (${code ?? signal})`);
    });
  }

  fail(message) {
    this.failure ??= new Error(message);
    for (const call of this.pending.values()) {
      clearTimeout(call.timer);
      call.reject(this.failure);
    }
    this.pending.clear();
  }

  send(message) {
    if (this.failure) throw this.failure;
    this.agent.stdin.write(`${JSON.stringify(message)}\n`);
  }

  reply({ id, method, params = {} }) {
    try {
      const callback = CALLBACKS[method];
      if (!callback) {
        return this.send({
          jsonrpc: "2.0",
          id,
          error: {
            code: -32601,
            message: `Unsupported client method: ${method}`,
          },
        });
      }
      this.send({ jsonrpc: "2.0", id, result: callback(params, this.cwd) });
    } catch (error) {
      try {
        this.send({
          jsonrpc: "2.0",
          id,
          error: {
            code: -32603,
            message: error.message ?? String(error),
          },
        });
      } catch (sendError) {
        this.fail(sendError.message ?? String(sendError));
      }
    }
  }

  onLine(line) {
    if (!line.trim()) return;
    let message;
    try {
      message = JSON.parse(line);
    } catch {
      return this.fail(`malformed ACP JSON: ${line.slice(0, 120)}`);
    }
    if (message.method && message.id != null) this.reply(message);
    else if (message.method === "session/update")
      this.updates.push(message.params?.update);
    else if (message.id != null) this.resolve(message);
  }

  resolve(message) {
    const call = this.pending.get(message.id);
    if (!call) return;
    clearTimeout(call.timer);
    this.pending.delete(message.id);
    if (message.error)
      call.reject(
        new Error(
          `ACP ${call.method} failed: ${message.error.message ?? JSON.stringify(message.error)}`,
        ),
      );
    else call.resolve(message.result);
  }

  rpc(method, params, timeoutMs = this.timeoutMs) {
    const id = this.nextId++;
    return new Promise((resolveCall, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`ACP ${method} timed out after ${timeoutMs}ms`));
      }, timeoutMs);
      this.pending.set(id, { method, resolve: resolveCall, reject, timer });
      try {
        this.send({ jsonrpc: "2.0", id, method, params });
      } catch (error) {
        clearTimeout(timer);
        this.pending.delete(id);
        reject(error);
      }
    });
  }

  async run({ model, prompt, setModel }) {
    await this.rpc("initialize", {
      protocolVersion: 1,
      clientCapabilities: { fs: { readTextFile: true, writeTextFile: true } },
      clientInfo: { name: "agents-adaptation-parity", version: "1" },
    });
    const session = await this.rpc("session/new", {
      cwd: this.cwd,
      mcpServers: [],
    });
    const sessionId = session?.sessionId ?? session?.session_id;
    if (!sessionId) throw new Error("ACP session/new returned no sessionId");
    if (setModel)
      await this.rpc("session/set_model", { sessionId, modelId: model });
    const result = await this.rpc("session/prompt", {
      sessionId,
      prompt: [{ type: "text", text: prompt }],
    });
    return { result, sessionId, updates: this.updates };
  }
}

function freshRequestCount(path, tag) {
  try {
    return readFileSync(path, "utf8")
      .split("\n")
      .filter(Boolean)
      .map(JSON.parse)
      .filter((record) => record.tag === tag && record.body instanceof Object)
      .length;
  } catch (error) {
    if (error.code === "ENOENT") return 0;
    throw error;
  }
}

export async function runAcpProbe(config) {
  let agent;
  let mock;
  writeFileSync(config.out, "");
  const home = mkdtempSync(join(tmpdir(), "agents-parity-home-"));
  try {
    mock = spawn(
      process.execPath,
      [join(config.scriptsDir, "mock_upstream.mjs")],
      {
        detached: process.platform !== "win32",
        env: {
          ...process.env,
          PORT: String(config.port),
          REQ_LOG: config.out,
          MOCK_TAG: config.tag,
          MOCK_CWD: config.cwd,
        },
        stdio: ["ignore", "ignore", "pipe"],
      },
    );
    await waitForMock(mock, config.port, config.readyTimeoutMs ?? 5000);
    const baseUrl = `http://127.0.0.1:${config.port}/v1`;
    agent = spawn(
      config.launch ? "/bin/sh" : process.execPath,
      config.launch ? ["-c", config.launch] : [config.server],
      {
        cwd: config.cwd,
        env: agentEnv(baseUrl, config.model, home),
        detached: process.platform !== "win32",
        stdio: ["pipe", "pipe", "inherit"],
      },
    );
    const result = await new AcpClient(agent, config.cwd, config.timeoutMs).run(
      config,
    );
    const upstreamRequests = freshRequestCount(config.out, config.tag);
    if (!upstreamRequests)
      throw new Error("agent completed without a fresh upstream request");
    return { ...result, upstreamRequests };
  } finally {
    await stop(agent);
    await stop(mock);
    rmSync(home, { recursive: true, force: true });
  }
}
