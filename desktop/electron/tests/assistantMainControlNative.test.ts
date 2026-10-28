import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it, vi } from "vitest";
import { AssistantHost } from "../src/assistant/assistantHost.js";
import { createAssistantProjectMainControl } from "../src/assistant/projectMainControl.js";
import { AssistantProjectRegistryConnection } from "../src/assistant/projectRegistryConnection.js";
import { parseDesktopCliArgs } from "../src/cli/desktopCli.js";
import { runWorkbenchLifecycle } from "../src/process/workbenchLifecycle.js";

// Actual Python HTTP/action transport and Windows Job, with a synthetic native
// identity. No provider, real user profile, project backend, UI or approval bypass
// claim: the fixture explicitly authorizes only its temporary lifecycle requests.
import { CHILD } from "./fixtures/assistantPrivateHost.js";

describe.skipIf(process.platform !== "win32")("real private main-control transport in Temp", () => {
  it("rejects new lifecycle writes across a full host restart without dispatching", async () => {
    const root = realpathSync.native(mkdtempSync(join(tmpdir(), "assistant-main-native-")));
    const sourceRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
    const gitEnv = Object.fromEntries(Object.entries(process.env).filter(([key]) => !key.toUpperCase().startsWith("GIT_")));
    const common = execFileSync("git", ["rev-parse", "--path-format=absolute", "--git-common-dir"], { cwd: sourceRoot, env: gitEnv, encoding: "utf8", windowsHide: true }).trim();
    const python = join(dirname(common), ".venv", "Scripts", "pythonw.exe");
    if (!existsSync(python)) throw new Error("Canonical validation Python is unavailable");
    let host: AssistantHost | undefined;
    try {
      const fixtureRoot = join(root, "fixture"); mkdirSync(join(fixtureRoot, "scripts"), { recursive: true });
      writeFileSync(join(fixtureRoot, "scripts", "assistant_host.py"), CHILD);
      const config = join(root, "operator.toml"); writeFileSync(config, "");
      const project = join(root, "synthetic-project"); mkdirSync(join(project, ".venv", "Scripts"), { recursive: true });
      writeFileSync(join(project, ".venv", "Scripts", "python.exe"), "never executed");
      const registry = new AssistantProjectRegistryConnection(join(root, "projects.json"));
      await registry.reconcile({ schemaVersion: 1, integrationRoot: project, items: [{ id: "main", path: project, checkedOut: true }] });
      const snapshot = registry.snapshot(), projectId = Object.keys(snapshot.projects)[0];
      const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => !key.toUpperCase().startsWith("VIBELUTION_") && !key.toUpperCase().startsWith("GIT_") && !key.toUpperCase().includes("API_KEY")));
      for (const [key, leaf] of Object.entries({ HOME: "home", USERPROFILE: "home", APPDATA: "roaming", LOCALAPPDATA: "local", TEMP: "temp", TMP: "temp", VIBELUTION_CONFIG_HOME: "config", VIBELUTION_DATA_HOME: "data", VIBELUTION_PROJECTS_HOME: "projects" })) {
        env[key] = join(root, leaf); mkdirSync(env[key], { recursive: true });
      }
      env.SYNTHETIC_SOURCE_ROOT = sourceRoot; env.VIBELUTION_CONFIG_PATH = config;
      env.VIBELUTION_CONFIG_HOME = root; env.ASSISTANT_TEST_WRITE_ROOT = root;
      const nativeRun = vi.fn(input => runWorkbenchLifecycle({ ...input,
        spawnImpl: () => { throw new Error("native guard must not spawn a backend"); },
        readState: () => ({ backendPid: 0, backendPort: 18000 }), writeState: () => undefined,
        listActiveWork: () => [{ kind: "chat_turn", runId: "synthetic-active", status: "running", sessionId: "synthetic-session" }],
        connect: async () => false, pidAlive: () => false,
      }));
      const launch = { env, cliArgs: parseDesktopCliArgs(["--assistant"]), resourcesRoot: fixtureRoot, userDataRoot: join(root, "user"), readTextFile: () => null };
      const makeHost = () => new AssistantHost({ profileRoot: join(root, "profile"), runtimeRoot: join(root, "runtime"), sourceRoot: fixtureRoot, pythonPath: python,
        env, projects: snapshot.projects, projectSnapshot: snapshot,
        mainControl: createAssistantProjectMainControl({ directory: join(root, "requests"), registry, launch, operatorConfigPath: config, runLifecycle: nativeRun, resolveDataHome: () => join(root, "target-data") }) });
      const send = async (action: string, operation: string, requestId: string) => host!.request({ operation: "send", requestId: `message-${requestId}`,
        message: JSON.stringify({ action, parameters: { project_id: projectId, operation, request_id: requestId } }) });
      host = makeHost(); await host.start();
      expect(await send("project_lifecycle", "stop", "native-stop")).toMatchObject({ state: "rejected", code: "prerequisite_required" });
      expect(await send("project_lifecycle", "restart", "native-restart")).toMatchObject({ state: "rejected", code: "prerequisite_required" });
      expect(nativeRun).not.toHaveBeenCalled();
      await host.stop(); host = makeHost(); await host.start();
      expect(await send("project_lifecycle_receipt", "restart", "native-restart")).toMatchObject({ state: "not_found", code: "request_not_found" });
      expect(await send("project_lifecycle", "restart", "native-restart")).toMatchObject({ state: "rejected", code: "prerequisite_required" });
      expect(nativeRun).not.toHaveBeenCalled();
      expect(readFileSync(config, "utf8")).toBe("");
    } catch (error) {
      // This synthetic child has no provider credentials or real profile. Keep
      // only a bounded diagnostic, never dump its environment or request data.
      const runtime = join(root, "runtime");
      const tails = existsSync(runtime) ? readdirSync(runtime).flatMap(name => {
        const path = join(runtime, name, "stderr.log");
        return existsSync(path) ? [readFileSync(path, "utf8").slice(-1800)] : [];
      }) : [];
      throw new Error(`Synthetic main-control child failed: ${error instanceof Error ? error.message : "unknown"}; ${tails.join("\n").slice(-2000)}`);
    } finally { await host?.stop(); rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 50 }); }
  }, 90_000);
});
