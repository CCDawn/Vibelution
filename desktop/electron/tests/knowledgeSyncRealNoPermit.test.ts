import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { expect, it } from "vitest";
import { InitialMigrationResults } from "../src/assistant/initialMigrationResults.js";
import { runInitialMigrationJob } from "../src/assistant/initialMigrationJob.js";
import { loadWorkbenchJobNative } from "../src/process/workbenchJob.js";
import type { PreHostSourceLease } from "../src/assistant/projectRegistryConnection.js";

it.skipIf(process.platform !== "win32")("records not_started after a real owned child drains without any permit", async () => {
  const python = execFileSync("python", ["-c", "import sys; print(sys.executable)"], { encoding: "utf8", windowsHide: true }).trim();
  const physicalTemp = execFileSync(python, ["-c", "import tempfile,pathlib; print(pathlib.Path(tempfile.gettempdir()).resolve())"],
    { encoding: "utf8", windowsHide: true }).trim();
  const root = mkdtempSync(join(physicalTemp, "knowledge-real-no-permit-"));
  const profile = join(root, "profile"), project = join(root, "project"), user = join(root, "user"), temp = join(root, "tmp");
  for (const path of [profile, project, user, temp, join(user, "local"), join(user, "roaming"), join(root, "projects")]) mkdirSync(path, { recursive: true });
  writeFileSync(join(profile, "host-owner.lock"), "0");
  const sourceConfig = join(root, "source.toml");
  writeFileSync(sourceConfig, ["[llm]", "schema_version = 2", "[llm.providers.local]", 'label = "Fixture"',
    'service_class = "local_runtime"', 'vendor = "custom"', 'driver = "openai"', 'base_url = "http://127.0.0.1:9/v1"',
    'auth_kind = "none"', 'credential_ref = "none"', "requires_credential = false", "[llm.providers.local.protocols]",
    'default = "chat_completions"', 'allowed = ["chat_completions"]', "[llm.providers.local.models.test]", 'upstream_id = "test"',
    'label = "Test"', "enabled = true", "context_window = 8192", "[llm.profiles.primary]", 'model_ref = "local/test"', ""].join("\n"));
  const pythonw = join(dirname(python), "pythonw.exe");
  expect(existsSync(pythonw)).toBe(true);
  const native = loadWorkbenchJobNative(), operationId = "ksync-" + "f".repeat(40), registryDigest = "b".repeat(64);
  const results = new InitialMigrationResults(join(root, "initial-migration-results"));
  let permits = 0;
  const lease: PreHostSourceLease = { revision: 1, signal: new AbortController().signal, check: () => undefined,
    registration: { baseProjectId: "project", registrationUuid: "uuid", integrationRoot: project, root: project, active: true },
    commit: async work => { permits++; return await work(); } };
  const env = { SYSTEMROOT: process.env.SYSTEMROOT, WINDIR: process.env.WINDIR, PATH: process.env.PATH,
    PATHEXT: process.env.PATHEXT, USERPROFILE: user, HOME: user, LOCALAPPDATA: join(user, "local"),
    APPDATA: join(user, "roaming"), TEMP: temp, TMP: temp, VIBELUTION_PROJECTS_HOME: join(root, "projects") };
  try {
    const configPath = join(profile, `.initial-migration-models-v1-${operationId}-${registryDigest}.toml`);
    const outcome = await runInitialMigrationJob({ lease, binding: { registeredProjectId: "project:uuid", sourceConfig,
      targetProfile: profile, targetConfig: configPath, operationId },
      sourceRoot: resolve(process.cwd(), "..", ".."), pythonPath: pythonw, pythonArguments: [], runtimeRoot: join(root, "runtime"),
      env, native, registryDigest, beforeSpawn: async () => { expect(await results.begin(operationId)).toBe(true); },
      onNotStarted: () => results.recordNotStarted(operationId) }).catch(error => {
        const dir = join(root, "runtime");
        const logs = existsSync(dir) ? readdirSync(dir).map(name => ["stdout.log", "stderr.log"].map(log => {
          const path = join(dir, name, log); return existsSync(path) ? readFileSync(path, "utf8") : "";
        }).join(" ")).join(" ") : "";
        throw new Error(`${String(error)} ${logs}`);
      });
    expect(permits).toBe(0);
    expect(outcome.state).toBe("not_started");
    expect(await new InitialMigrationResults(join(root, "initial-migration-results")).get(operationId)).toBe("not_started");
    expect(existsSync(join(profile, "initial_migration_claims", operationId))).toBe(false);
    execFileSync(python, ["-c", "import sys; from core.assistant_runtime.knowledge_not_started import read_verified_not_started; assert read_verified_not_started(sys.argv[1],sys.argv[2])", profile, operationId],
      { cwd: resolve(process.cwd(), "..", ".."), env, encoding: "utf8", windowsHide: true });
    const cancelled = "ksync-" + "e".repeat(40), controller = new AbortController();
    let writerStarts = 0;
    const observingNative = { ...native, spawn: (input: Parameters<typeof native.spawn>[0]) => {
      if (!input.arguments.includes("--knowledge-preflight")) writerStarts++;
      return native.spawn(input);
    } };
    await expect(runInitialMigrationJob({ lease, binding: { registeredProjectId: "project:uuid", sourceConfig,
      targetProfile: profile, targetConfig: join(profile, `.initial-migration-models-v1-${cancelled}-${registryDigest}.toml`), operationId: cancelled },
      sourceRoot: resolve(process.cwd(), "..", ".."), pythonPath: pythonw, pythonArguments: [], runtimeRoot: join(root, "runtime"),
      env, native: observingNative, signal: controller.signal, registryDigest, beforeSpawn: async () => {
        const pending = results.begin(cancelled);
        controller.abort();
        expect(await pending).toBe(true);
      }, onNotStarted: () => results.recordNotStarted(cancelled) })).rejects.toThrow();
    expect(writerStarts).toBe(0);
    expect(await new InitialMigrationResults(join(root, "initial-migration-results")).get(cancelled)).toBe("not_started");
    execFileSync(python, ["-c", "import sys; from core.assistant_runtime.knowledge_not_started import read_verified_not_started; assert read_verified_not_started(sys.argv[1],sys.argv[2])", profile, cancelled],
      { cwd: resolve(process.cwd(), "..", ".."), env, encoding: "utf8", windowsHide: true });
  } finally { rmSync(root, { recursive: true, force: true }); }
}, 60000);
