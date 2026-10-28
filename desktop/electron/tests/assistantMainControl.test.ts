import { mkdirSync, mkdtempSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AssistantProjectRegistryConnection } from "../src/assistant/projectRegistryConnection.js";
import { createAssistantProjectMainControl } from "../src/assistant/projectMainControl.js";
import { parseDesktopCliArgs } from "../src/cli/desktopCli.js";
import { waitForMainLineIntentPersistence } from "../src/lifecycle/mainLine/commandQueue.js";
import { runWorkbenchLifecycle, type RunWorkbenchLifecycleInput } from "../src/process/workbenchLifecycle.js";

const roots: string[] = [];
afterEach(() => { vi.unstubAllEnvs(); for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true, maxRetries: 10 }); });
const nativePath = (path: string) => { const real = realpathSync.native(path); return process.platform === "win32" ? real.toLowerCase() : real; };
async function setup() {
  const root = nativePath(mkdtempSync(join(tmpdir(), "assistant-main-control-"))); roots.push(root);
  const project = join(root, "project"), branch = join(root, "branch"); mkdirSync(project); mkdirSync(branch);
  mkdirSync(join(project, ".venv", "Scripts"), { recursive: true });
  const pythonPath = join(project, ".venv", "Scripts", "python.exe"); writeFileSync(pythonPath, "fake");
  const configPath = join(root, "operator.toml"); writeFileSync(configPath, "");
  const registry = new AssistantProjectRegistryConnection(join(root, "registry.json"));
  await registry.reconcile({ schemaVersion: 1, integrationRoot: project, items: [
    { id: "main", path: project, checkedOut: true }, { id: "branch", path: branch, checkedOut: true },
  ] });
  const mainId = Object.entries(registry.snapshot().projects).find(([, path]) => path === project)![0];
  const branchId = Object.entries(registry.snapshot().projects).find(([, path]) => path === branch)![0];
  const execute = vi.fn(async (input: RunWorkbenchLifecycleInput) => input.queue!.submit({ operation: input.operation,
    execute: async command => { await waitForMainLineIntentPersistence(command); return { schemaVersion: 1, accepted: true, operation: command.operation, commandId: command.commandId }; } }));
  const launch = { env: { VIBELUTION_PORT: "19500", VIBELUTION_DATA_HOME: join(root, "other-project-data"), VIBELUTION_WEB_CONTROL_TOKEN: "synthetic-secret", PYTHON: "other-python" },
    cliArgs: parseDesktopCliArgs(["--assistant"]), userDataRoot: join(root, "user"), resourcesRoot: join(root, "resources"), readTextFile: () => null };
  const create = () => createAssistantProjectMainControl({ directory: join(root, "requests"), registry, launch, operatorConfigPath: configPath,
    runLifecycle: execute, readStatusSummary: () => ({ backendHealthy: false, backendPortListening: false, observedState: "closed", overallState: "idle", lifecycleConsistency: "aligned", phase: "idle", stateVersion: 1, lifecycleResults: [] }),
    resolveDataHome: () => join(root, "target-data") });
  const request = { deliveryId: "a".repeat(32), action: "project_lifecycle" as const, projectId: mainId, operation: "start" as const, requestId: "synthetic-request" };
  return { root, project, branch, registry, mainId, branchId, configPath, pythonPath, execute, create, request };
}

describe("production main control composition", () => {
  it("exposes the native queue's actual execution drain through the assistant guard", async () => {
    const f = await setup();
    let entered!: () => void, release!: () => void;
    let capture!: () => Promise<void>;
    const started = new Promise<void>(resolve => { entered = resolve; });
    const gate = new Promise<void>(resolve => { release = resolve; });
    f.execute.mockImplementationOnce(input => {
      capture = input.queue!.captureExecutionDrain!;
      return input.queue!.submit({ operation: input.operation, execute: async command => {
        entered(); await gate;
        return { schemaVersion: 1, accepted: true, operation: command.operation, commandId: command.commandId };
      } });
    });
    const request = f.create()(f.request);
    await started;
    let drained = false;
    const drain = capture().then(() => { drained = true; });
    await Promise.resolve();
    expect(drained).toBe(false);
    release();
    await request;
    await drain;
    expect(drained).toBe(true);
  });
  it("joins the assistant and ordinary Launcher controls on the same native command", async () => {
    const f = await setup();
    let entered!: () => void, release!: () => void;
    const started = new Promise<void>(resolve => { entered = resolve; });
    const gate = new Promise<void>(resolve => { release = resolve; });
    let commandId = "";
    f.execute.mockImplementationOnce(input => input.queue!.submit({ operation: input.operation, noBrowser: true, execute: async command => {
      commandId = command.commandId; entered(); await gate;
      return { schemaVersion: 1, accepted: true, operation: command.operation, commandId: command.commandId };
    } }));
    const assistant = f.create()({ ...f.request, operation: "restart" });
    await started;
    const spawn = vi.fn(() => { throw new Error("must join the assistant command"); });
    const ordinary = runWorkbenchLifecycle({ workspaceRoot: f.project, pythonPath: f.pythonPath, operatorConfigPath: f.configPath,
      operation: "restart", spawnImpl: spawn });
    release();
    const [, result] = await Promise.all([assistant, ordinary]);
    expect(result.commandId).toBe(commandId);
    expect(spawn).not.toHaveBeenCalled();
    expect(f.execute).toHaveBeenCalledTimes(1);
  });
  it("uses the current registered main target and explicit config/environment without changing global state", async () => {
    const f = await setup(), control = f.create();
    const before = process.env.VIBELUTION_WORKSPACE_ROOT;
    expect(await control(f.request)).toMatchObject({ state: "unknown", code: "receipt_unavailable" });
    const input = f.execute.mock.calls[0][0];
    expect(input.workspaceRoot).toBe(f.project); expect(input.pythonPath).toBe(f.pythonPath);
    expect(input.operatorConfigPath).toBe(f.configPath);
    expect(input.targetEnvironment?.VIBELUTION_CONFIG_PATH).toBe(f.configPath);
    expect(input.targetEnvironment?.VIBELUTION_DATA_HOME).toBe(join(f.root, "target-data"));
    expect(input.targetEnvironment?.VIBELUTION_PORT).toBeUndefined();
    expect(input.targetEnvironment?.VIBELUTION_WEB_CONTROL_TOKEN).toBeUndefined();
    expect(process.env.VIBELUTION_WORKSPACE_ROOT).toBe(before);
    expect(await f.create()(f.request)).toMatchObject({ state: "unknown" });
    expect(f.execute).toHaveBeenCalledTimes(1);
  });

  it("uses persisted registration metadata, refuses branch instance writes and does not infer a main root", async () => {
    const f = await setup();
    expect(f.registry.registration(f.branchId)?.integrationRoot).toBe(f.project);
    expect(await f.create()({ ...f.request, projectId: f.branchId })).toMatchObject({ state: "rejected", code: "prerequisite_required" });
    expect(await f.create()({ deliveryId: "b".repeat(32), projectId: f.branchId, action: "project_status", operation: "status" }))
      .toMatchObject({ accepted: false, code: "prerequisite_required" });
    expect(f.execute).not.toHaveBeenCalled();
  });

  it("reads canonical native status without starting a project and denies a closed registry", async () => {
    const f = await setup(), control = f.create();
    expect(await control({ deliveryId: "b".repeat(32), action: "project_status", projectId: f.mainId, operation: "status" }))
      .toMatchObject({ accepted: true, code: "status", status: { state: "stopped" } });
    expect(f.execute).not.toHaveBeenCalled();
    await f.registry.stop();
    expect(() => f.registry.snapshot()).toThrow();
    expect(await control(f.request)).toMatchObject({ state: "rejected", code: "project_unavailable" });
  });
});
