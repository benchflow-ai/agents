// Hermetic ACP routing smoke for trusted POSIX shell launch command.
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { option, positiveNumber, runAcpProbe } from "./acp_driver.mjs";

try {
  const argv = process.argv;
  const launch = option(argv, "launch");
  if (!launch) throw new Error("usage: --launch <trusted POSIX shell command>");
  const cwd = option(argv, "cwd", mkdtempSync(join(tmpdir(), "smoke-")));
  const result = await runAcpProbe({
    scriptsDir: dirname(fileURLToPath(import.meta.url)),
    launch,
    cwd,
    out: join(cwd, "upstream.jsonl"),
    port: positiveNumber(option(argv, "port", "11700"), "port", {
      integer: true,
      max: 65535,
    }),
    model: option(argv, "model", "deepseek-v4-flash"),
    prompt: "Create a file hello.txt with exactly: Hello, world!",
    timeoutMs: positiveNumber(
      option(argv, "rpc-timeout", "25000"),
      "rpc-timeout",
    ),
    readyTimeoutMs: positiveNumber(
      option(argv, "ready-timeout", "5000"),
      "ready-timeout",
    ),
    setModel: argv.includes("--set-model"),
    tag: "smoke",
  });
  console.log(
    JSON.stringify({
      upstreamRequests: result.upstreamRequests,
      initOk: true,
      sessionId: result.sessionId,
      stopReason: result.result?.stopReason ?? null,
    }),
  );
} catch (error) {
  console.error(`acp_smoke: ${error.message ?? error}`);
  process.exitCode = error.message?.startsWith("usage:") ? 2 : 1;
}
