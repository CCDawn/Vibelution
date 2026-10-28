import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { createServer } from "node:http";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { AssistantHost } from "../src/assistant/assistantHost.js";
import { loadWorkbenchJobNative } from "../src/process/workbenchJob.js";

describe.skipIf(process.platform !== "win32")("real assistant host migration barrier in Temp", () => {
  it("naturally drains the owned Job and preserves an unaccepted message and ID across restart", async () => {
    const root = realpathSync.native(mkdtempSync(join(tmpdir(), "assistant-migration-host-")));
    const sourceRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
    const gitEnv = Object.fromEntries(Object.entries(process.env).filter(([key]) => !key.toUpperCase().startsWith("GIT_")));
    const common = execFileSync("git", ["rev-parse", "--path-format=absolute", "--git-common-dir"],
      { cwd: sourceRoot, env: gitEnv, encoding: "utf8", windowsHide: true }).trim();
    const python = join(dirname(common), ".venv", "Scripts", "pythonw.exe");
    if (!existsSync(python)) throw new Error("Canonical validation Python is unavailable");
    const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => !key.toUpperCase().startsWith("VIBELUTION_")
      && !key.toUpperCase().startsWith("GIT_") && !key.toUpperCase().includes("API_KEY")));
    for (const [key, leaf] of Object.entries({ HOME: "home", USERPROFILE: "home", APPDATA: "roaming", LOCALAPPDATA: "local",
      TEMP: "temp", TMP: "temp", VIBELUTION_CONFIG_HOME: "config", VIBELUTION_DATA_HOME: "data", VIBELUTION_PROJECTS_HOME: "projects" })) {
      env[key] = join(root, leaf); mkdirSync(env[key], { recursive: true });
    }
    const config = join(root, "config", "config.toml");
    const provider = createServer((request, response) => {
      request.resume();
      request.on("end", () => {
        response.writeHead(200, { "content-type": "text/event-stream" });
        response.end('data: {"id":"fixture","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"role":"assistant","content":"收到。"},"finish_reason":null}]}\n\ndata: {"id":"fixture","object":"chat.completion.chunk","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n');
      });
    });
    await new Promise<void>(done => provider.listen(0, "127.0.0.1", done));
    const address = provider.address();
    if (!address || typeof address === "string") throw new Error("Isolated provider unavailable");
    writeFileSync(config, ['[llm]', 'schema_version = 2', '[llm.providers.local]', 'label = "Isolated"',
      'service_class = "local_runtime"', 'vendor = "custom"', 'driver = "openai"', `base_url = "http://127.0.0.1:${address.port}/v1"`,
      'auth_kind = "none"', 'credential_ref = "none"', 'requires_credential = false', '[llm.providers.local.protocols]',
      'default = "chat_completions"', 'allowed = ["chat_completions"]', '[llm.providers.local.models.test]',
      'upstream_id = "test"', 'label = "Test"', 'enabled = true', 'context_window = 8192',
      '[llm.profiles.primary]', 'model_ref = "local/test"', ''].join('\n'));
    env.VIBELUTION_CONFIG_PATH = config;
    const writes: unknown[] = [];
    const fetchImpl: typeof fetch = async (input, init) => {
      if (String(input).endsWith("/api/assistant/messages")) writes.push(JSON.parse(String(init?.body)));
      return await fetch(input, init);
    };
    const actual = loadWorkbenchJobNative();
    let terminations = 0;
    const native = { spawn: actual.spawn, activeCount: actual.activeCount, drainStatus: actual.drainStatus,
      exitCode: actual.exitCode, close: actual.close, terminate: (job: object) => { terminations++; return actual.terminate(job); } };
    const host = new AssistantHost({ profileRoot: join(root, "profile"), runtimeRoot: join(root, "runtime"), sourceRoot,
      pythonPath: python, projects: {}, env, fetch: fetchImpl, native });
    let admission: ReturnType<AssistantHost["beginMigrationAdmission"]> | undefined;
    try {
      await host.start();
      admission = host.beginMigrationAdmission();
      await admission.seal();
      expect(await host.migrationBarrier("prepare")).toBe("probing");
      let status = await host.migrationBarrier("status");
      const deadline = Date.now() + 30_000;
      while (status === "probing" && Date.now() < deadline) {
        await new Promise(done => setTimeout(done, 100));
        status = await host.migrationBarrier("status");
      }
      expect(status).toBe("ready");
      const pending = host.request({ operation: "send", message: "请记住这个测试请求。", requestId: "original-request-id" });
      expect(writes).toHaveLength(0);
      let retired = await host.retireForMigration();
      while (!retired && Date.now() < deadline) {
        await new Promise(done => setTimeout(done, 100));
        retired = await host.retireForMigration();
      }
      expect(retired).toBe(true);
      expect(terminations).toBe(0);
      host.prepareForMigrationRestart({ schemaVersion: 1, revision: 0, projects: {} }, false);
      await host.startForMigration();
      admission.release(); admission = undefined;
      expect(await pending).toMatchObject({ accepted: true });
      expect(writes).toEqual([{ message: "请记住这个测试请求。", requestId: "original-request-id" }]);
    } finally {
      admission?.release();
      try { await host.stop(); }
      finally {
        await new Promise<void>(done => provider.close(() => done()));
        rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 50 });
      }
    }
  }, 90_000);
});
