// Drive one ACP turn against deterministic OpenAI-compatible mock.
import { existsSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { option, positiveNumber, runAcpProbe } from "./acp_driver.mjs";

try {
  const argv = process.argv;
  const server = option(argv, "server");
  const launch = option(argv, "launch");
  if (Boolean(server) === Boolean(launch))
    throw new Error(
      "usage: (--server <server.mjs> | --launch <trusted POSIX shell command>) --out <log> [--port --model --cwd --prompt --rpc-timeout --ready-timeout --set-model]",
    );
  const cwd = option(argv, "cwd", mkdtempSync(join(tmpdir(), "parity-")));
  const out = option(argv, "out", "/tmp/parity-outside.jsonl");
  const result = await runAcpProbe({
    scriptsDir: dirname(fileURLToPath(import.meta.url)),
    server,
    launch,
    cwd,
    out,
    port: positiveNumber(option(argv, "port", "11500"), "port", {
      integer: true,
      max: 65535,
    }),
    model: option(argv, "model", "mock-model"),
    prompt: option(
      argv,
      "prompt",
      "Create a file named hello.txt in the current directory containing exactly: Hello, world!",
    ),
    timeoutMs: positiveNumber(
      option(argv, "rpc-timeout", "25000"),
      "rpc-timeout",
    ),
    readyTimeoutMs: positiveNumber(
      option(argv, "ready-timeout", "5000"),
      "ready-timeout",
    ),
    setModel: argv.includes("--set-model"),
    tag: "capture",
  });
  const hello = join(cwd, "hello.txt");
  console.log(
    JSON.stringify(
      {
        upstreamLog: out,
        upstreamRequests: result.upstreamRequests,
        stopReason: result.result?.stopReason,
        toolCalls: result.updates
          .filter((update) => update?.sessionUpdate === "tool_call")
          .map((update) => update.title),
        fileWritten: existsSync(hello) ? readFileSync(hello, "utf8") : null,
      },
      null,
      2,
    ),
  );
} catch (error) {
  console.error(`acp_capture: ${error.message ?? error}`);
  process.exitCode = error.message?.startsWith("usage:") ? 2 : 1;
}
