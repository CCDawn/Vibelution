import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, realpathSync, rmSync, writeFileSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AssistantProjectRegistryConnection } from "../src/assistant/projectRegistryConnection.js";
import { createAssistantProjectMainControl } from "../src/assistant/projectMainControl.js";
import { createAssistantProjectLifecycle } from "../src/assistant/projectLifecycle.js";
import { AssistantProjectLifecycleRequestStore } from "../src/assistant/projectLifecycleRequestStore.js";
import { mainLineCommandResultPath } from "../src/lifecycle/mainLine/commandEvidence.js";
import { parseDesktopCliArgs } from "../src/cli/desktopCli.js";
import { waitForMainLineIntentPersistence } from "../src/lifecycle/mainLine/commandQueue.js";
import { resolveRuntimeManagerDir } from "../src/lifecycle/projectStoragePaths.js";
import { runWorkbenchLifecycle, type RunWorkbenchLifecycleInput } from "../src/process/workbenchLifecycle.js";

const roots: string[] = [];
afterEach(() => { vi.unstubAllEnvs(); for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true, maxRetries: 10 }); });
const nativePath = (path: string) => { const real = realpathSync.native(path); return process.platform === "win32" ? real.toLowerCase() : real; };
async function setup() {
  const root = nativePath(mkdtempSync(join(tmpdir(), "assistant-main-control-"))); roots.push(root);
  const project = join(root, "project"), branch = join(root, "branch"); mkdirSync(project); mkdirSync(branch);
  mkdirSync(join(project, ".venv", "Scripts"), { recursive: true });
  const pythonPath = join(project, ".venv", "Scripts", "python.exe"); writeFileSync(pythonPath, "fake");
  const configPath = join(root, "operator.toml");
  writeFileSync(configPath, `[storage]\ndata_home = ${JSON.stringify(join(root, "target-data"))}\n`);
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
    runLifecycle: execute, readStatusSummary: () => ({ backendHealthy: false, backendPortListening: false, observedState: "closed", overallState: "idle", lifecycleConsistency: "aligned", phase: "idle", stateVersion: 1, lifecycleResults: [] }) });
  const request = { deliveryId: "a".repeat(32), action: "project_lifecycle" as const, projectId: mainId, operation: "start" as const, requestId: "synthetic-request" };
  return { root, project, branch, registry, mainId, branchId, configPath, pythonPath, execute, create, request };
}

describe("production main control composition", () => {
  it.skipIf(process.platform !== "win32")("preserves the configured native data owner when starting a registered project", async () => {
    const f = await setup();
    mkdirSync(join(f.project, ".vibelution"));
    writeFileSync(join(f.project, ".vibelution", "project.json"), JSON.stringify({ schemaVersion: 1, projectId: "synthetic-data-owner" }));
    await f.create()(f.request);
    const input = f.execute.mock.calls[0][0];
    const sourceRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
    const inherited = Object.fromEntries(Object.entries(process.env).filter(([key]) => !key.toUpperCase().startsWith("GIT_")
      && !key.toUpperCase().startsWith("VIBELUTION_") && !["PYTHONPATH", "PYTHONHOME"].includes(key.toUpperCase())));
    const common = execFileSync("git", ["rev-parse", "--path-format=absolute", "--git-common-dir"],
      { cwd: sourceRoot, env: inherited, encoding: "utf8", windowsHide: true }).trim();
    const python = join(dirname(common), ".venv", "Scripts", "python.exe");
    const observed = execFileSync(python, ["-X", "utf8", "-c",
      "import sys; from vibelution_storage import resolve_project_data_home; print(resolve_project_data_home(sys.argv[1]))", f.project],
      { cwd: sourceRoot, env: { ...inherited, ...input.targetEnvironment }, encoding: "utf8", windowsHide: true }).trim();
    expect(resolve(observed).toLowerCase()).toBe(resolve(f.root, "target-data").toLowerCase());
    expect(input.targetEnvironment?.VIBELUTION_DATA_HOME).toBeUndefined();
    expect(input.targetEnvironment?.VIBELUTION_CONFIG_PATH).toBe(f.configPath);
  });
  it("recovers the original native start after a real unrelated inventory refresh and facade restart", async () => {
    const f = await setup();
    f.execute.mockImplementationOnce(input => input.queue!.submit({ operation: input.operation, execute: async command => {
      await waitForMainLineIntentPersistence(command);
      const manager = resolveRuntimeManagerDir(input.workspaceRoot);
      mkdirSync(join(manager, "results"), { recursive: true });
      writeFileSync(mainLineCommandResultPath(manager, command.commandId), JSON.stringify({ schemaVersion: 1, source: "electron_main",
        commandId: command.commandId, type: command.type, operation: command.operation, accepted: true, ok: true, completed: true,
        startedAt: "2026-11-02T06:01:53Z", settledAt: "2026-11-02T06:01:55Z", runMs: 2000 }));
      await f.registry.reconcile({ schemaVersion: 1, integrationRoot: f.project, items: [{ id: "main", path: f.project, checkedOut: true }] });
      return { schemaVersion: 1, accepted: true, operation: command.operation, commandId: command.commandId };
    } }));
    expect(await f.create()(f.request)).toMatchObject({ state: "completed", accepted: true });
    const store = new AssistantProjectLifecycleRequestStore({ directory: join(f.root, "requests") });
    const before = await store.get(f.request.requestId);
    expect(await f.create()({ ...f.request, action: "project_lifecycle_receipt" })).toMatchObject({ state: "completed", accepted: true });
    expect(await f.create()(f.request)).toMatchObject({ state: "completed", accepted: true });
    expect(await store.get(f.request.requestId)).toEqual(before);
    expect(f.execute).toHaveBeenCalledTimes(1);
    await f.registry.reconcile({ schemaVersion: 1, integrationRoot: f.project, items: [] });
    const denied = await f.create()({ ...f.request, action: "project_lifecycle_receipt" }) as Record<string, unknown>;
    expect(denied).toMatchObject({ state: "unknown", code: "project_unavailable" });
    expect(denied.accepted).toBeUndefined();
    await f.registry.reconcile({ schemaVersion: 1, integrationRoot: f.project, items: [{ id: "main", path: f.project, checkedOut: true }] });
    const newId = Object.entries(f.registry.snapshot().projects).find(([, path]) => path === f.project)![0];
    expect(newId).not.toBe(f.mainId); // Same physical root does not revive an old registration UUID.
    expect(await f.create()({ ...f.request, action: "project_lifecycle_receipt" })).toMatchObject({ state: "unknown", code: "project_unavailable" });
    expect(await store.get(f.request.requestId)).toEqual(before);
    expect(f.execute).toHaveBeenCalledTimes(1);
  });

  it.each(["start", "stop", "restart"] as const)("reserves and dispatches new %s to the native runner", async operation => {
    const f = await setup(), control = f.create();
    expect(await control({ ...f.request, operation })).toMatchObject({ state: "unknown", code: "receipt_unavailable" });
    expect(readdirSync(join(f.root, "requests")).length).toBeGreaterThan(0);
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
    expect(input.targetEnvironment?.VIBELUTION_DATA_HOME).toBeUndefined();
    expect(input.targetEnvironment?.VIBELUTION_PORT).toBeUndefined();
    expect(input.targetEnvironment?.VIBELUTION_WEB_CONTROL_TOKEN).toBeUndefined();
    expect(process.env.VIBELUTION_WORKSPACE_ROOT).toBe(before);
    expect(await f.create()(f.request)).toMatchObject({ state: "unknown" });
    expect(f.execute).toHaveBeenCalledTimes(1);
  });
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
  it("holds the main-line exclusive fence against ordinary Launcher controls during assistant restart", async () => {
    const f = await setup();
    let entered!: () => void, release!: () => void;
    const started = new Promise<void>(resolve => { entered = resolve; });
    const gate = new Promise<void>(resolve => { release = resolve; });
    f.execute.mockImplementation(input => input.queue!.submit({ operation: input.operation, execute: async command => {
      entered(); await gate;
      return { schemaVersion: 1, accepted: true, operation: command.operation, commandId: command.commandId };
    } }));
    const assistant = f.create()({ ...f.request, operation: "restart" });
    await started;
    const spawn = vi.fn(() => { throw new Error("must not run while the assistant fence is held"); });
    await expect(runWorkbenchLifecycle({ workspaceRoot: f.project, pythonPath: f.pythonPath, operatorConfigPath: f.configPath,
      operation: "restart", spawnImpl: spawn })).rejects.toThrow("MAIN_LINE_EXCLUSIVE_BUSY");
    expect(spawn).not.toHaveBeenCalled();
    release();
    expect(await assistant).toMatchObject({ state: "unknown", code: "receipt_unavailable" });
    expect(f.execute).toHaveBeenCalledTimes(1);
  });
  it("reads a previous completed receipt after recreation without redispatch", async () => {
    const f = await setup();
    const identity = { requestId: f.request.requestId, projectId: f.mainId, operation: "start" as const };
    const facade = createAssistantProjectLifecycle({ getPermissionSnapshot: () => f.registry.snapshot(),
      resolveRuntimeContext: async () => null, readStatus: async () => ({ state: "stopped" }) });
    const binding = facade.bindingFor(f.mainId);
    const store = new AssistantProjectLifecycleRequestStore({ directory: join(f.root, "requests") });
    const reservation = await store.reserve(identity);
    await store.bind(identity, reservation.reservationToken!, binding, { commandId: "cmd_previous", type: "open", operation: "start" });
    const path = mainLineCommandResultPath(binding.runtimeManagerDir, "cmd_previous");
    mkdirSync(join(binding.runtimeManagerDir, "results"), { recursive: true });
    writeFileSync(path, JSON.stringify({ schemaVersion: 1, source: "electron_main", commandId: "cmd_previous",
      type: "open", operation: "start", accepted: true, ok: true, completed: true,
      startedAt: "2026-10-26T00:00:00Z", settledAt: "2026-10-26T00:00:01Z", runMs: 1000 }));
    const control = f.create();
    expect(await control({ ...f.request, action: "project_lifecycle_receipt" })).toMatchObject({ state: "completed", code: "accepted" });
    expect(await f.create()(f.request)).toMatchObject({ state: "completed", code: "accepted" });
    expect(await control({ ...f.request, operation: "stop" })).toMatchObject({ state: "rejected", code: "request_conflict" });
    expect(f.execute).not.toHaveBeenCalled();
  });

  it("retains an unknown old request without creating or executing another", async () => {
    const f = await setup();
    const store = new AssistantProjectLifecycleRequestStore({ directory: join(f.root, "requests") });
    await store.reserve({ requestId: f.request.requestId, projectId: f.mainId, operation: "start" });
    expect(await f.create()(f.request)).toMatchObject({ state: "unknown", code: "request_unbound" });
    expect(f.execute).not.toHaveBeenCalled();
  });

  it("leaves ordinary Launcher lifecycle active-work behavior unchanged", async () => {
    const f = await setup(), spawn = vi.fn();
    const result = await runWorkbenchLifecycle({ workspaceRoot: f.project, pythonPath: f.pythonPath, operatorConfigPath: f.configPath,
      operation: "stop", spawnImpl: spawn,
      listActiveWork: () => [{ kind: "chat_turn", runId: "active", status: "running", sessionId: "session" }] });
    expect(result).toMatchObject({ accepted: false, code: "active_work_blocked" });
    expect(spawn).not.toHaveBeenCalled(); expect(f.execute).not.toHaveBeenCalled();
  });

  it("uses persisted registration metadata, refuses branch instance writes and does not infer a main root", async () => {
    const f = await setup();
    expect(f.registry.registration(f.branchId)?.integrationRoot).toBe(f.project);
    expect(await f.create()({ ...f.request, projectId: f.branchId })).toMatchObject({ state: "unknown", code: "prerequisite_required" });
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
    expect(await control(f.request)).toMatchObject({ state: "unknown", code: "project_unavailable" });
  });
});
