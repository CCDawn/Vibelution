import { existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createAssistantProjectMainControl } from "../src/assistant/projectMainControl.js";
import { AssistantProjectRegistryConnection } from "../src/assistant/projectRegistryConnection.js";
import { AssistantProjectLifecycleRequestStore } from "../src/assistant/projectLifecycleRequestStore.js";
import { createBranchLifecycleCommandOwner, resolveBranchLifecycleTarget, assertBranchLifecycleIdle,
  branchCommandResultPath, type BranchLifecycleResult } from "../src/lifecycle/branchLifecycleCommands.js";
import { LauncherLifecycleSupervisor } from "../src/lifecycle/launcherLifecycleSupervisor.js";
import { claimStart, claimStop, completeStop, observeReady, readRegistry } from "../src/lifecycle/instanceRegistryStore.js";
import { retireIsolatedRuntimeBeforeStart } from "../src/lifecycle/isolatedInstanceRegistryHost.js";
import { parseDesktopCliArgs } from "../src/cli/desktopCli.js";
import { readNativeBranchInstanceInventory } from "../src/process/branchInstanceInventory.js";

const roots: string[] = [];
afterEach(() => { vi.unstubAllEnvs(); for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true, maxRetries: 10 }); });
const physical = (path: string) => { const root = realpathSync.native(path); return process.platform === "win32" ? root.toLowerCase() : root; };
const defer = () => { let release!: () => void; return { promise: new Promise<void>(resolve => { release = resolve; }), release: () => release() }; };

async function setup() {
  const root = physical(mkdtempSync(join(tmpdir(), "assistant-branch-native-"))); roots.push(root);
  const main = join(root, "main"), branch = join(root, "branch"), otherMain = join(root, "other-main"), otherBranch = join(root, "other-branch");
  for (const path of [main, branch, otherMain, otherBranch]) mkdirSync(path);
  const config = join(root, "operator.toml"); writeFileSync(config, "");
  const registry = new AssistantProjectRegistryConnection(join(root, "projects.json"));
  const inventories = new Map([
    [main, { schemaVersion: 1, integrationRoot: main, items: [{ id: "main", path: main, checkedOut: true, alive: false },
      { id: "worktree:one", path: branch, checkedOut: true, alive: false }] }],
    [otherMain, { schemaVersion: 1, integrationRoot: otherMain, items: [{ id: "main", path: otherMain, checkedOut: true, alive: false },
      { id: "worktree:two", path: otherBranch, checkedOut: true, alive: false }] }],
  ]);
  for (const [integrationRoot, inventory] of inventories) await registry.reconcile(inventory);
  const idFor = (path: string) => Object.entries(registry.snapshot().projects).find(([, registered]) => registered === path)![0];
  const branchId = idFor(branch), otherBranchId = idFor(otherBranch);
  const instancesPath = join(root, "instances.json");
  const supervisor = new LauncherLifecycleSupervisor();
  const nativeEffect = vi.fn();
  const readInventory = vi.fn(async (integrationRoot: string) => inventories.get(integrationRoot));
  let beforeEffect: (() => Promise<void>) | undefined;
  let nativeFailure: BranchLifecycleResult | undefined;
  const owner = createBranchLifecycleCommandOwner({
    resolveTarget: async (workspaceRoot, integrationRoot) => {
      if (!integrationRoot) return null;
      const inventory = await readInventory(integrationRoot);
      return resolveBranchLifecycleTarget(inventory, workspaceRoot);
    },
    run: async input => {
      assertBranchLifecycleIdle(supervisor, input.target.instanceId);
      const lease = supervisor.beginIntent({ instanceId: input.target.instanceId, operation: input.operation,
        desiredState: input.operation === "stop" ? "closed" : "open" });
      const mutation = await supervisor.executeMutation({ lease, reconcile: async () => {}, mutate: async () => {
        await input.execution.onCommand();
        await beforeEffect?.();
        input.execution.check();
        if (nativeFailure) return { ...nativeFailure, operation: input.operation, instanceId: input.target.instanceId };
        nativeEffect(input.target.workspaceRoot, input.operation);
        if (input.operation === "stop") {
          const claimed = await claimStop(instancesPath, { instanceId: input.target.instanceId, projectRoot: input.target.workspaceRoot,
            expectedProjectRoot: input.target.workspaceRoot, commandId: input.execution.command.commandId });
          await completeStop(instancesPath, { instanceId: input.target.instanceId, expectedGeneration: claimed.entry.generation });
        } else {
          const claimed = await claimStart(instancesPath, { instanceId: input.target.instanceId, projectRoot: input.target.workspaceRoot,
            expectedProjectRoot: input.target.workspaceRoot, operation: input.operation, commandId: input.execution.command.commandId,
            deadlineAt: new Date(Date.now() + 60000).toISOString(), ownerPid: process.pid, portIsFree: () => true });
          if (!claimed.ok) throw new Error("instance busy");
          await observeReady(instancesPath, { instanceId: input.target.instanceId, expectedGeneration: claimed.entry.generation });
        }
        return { schemaVersion: 1 as const, accepted: true, operation: input.operation, instanceId: input.target.instanceId,
          commandId: input.execution.command.commandId };
      } });
      if (mutation.outcome !== "committed") { supervisor.clearSlotIfCurrent(lease); throw new Error("native outcome unknown"); }
      const current = supervisor.bindCommand(lease, { commandId: input.execution.command.commandId });
      if (current && input.operation !== "stop") { supervisor.claimReady(current); supervisor.completeReady(current); }
      if (!mutation.value.accepted) supervisor.clearSlotIfCurrent(lease);
      return mutation.value;
    },
  });
  const mainRun = vi.fn();
  const control = () => createAssistantProjectMainControl({ directory: join(root, "requests"), registry,
    operatorConfigPath: config, launch: { env: {}, cliArgs: parseDesktopCliArgs(["--assistant"]), resourcesRoot: root, userDataRoot: root },
    runLifecycle: mainRun, branchOwner: owner });
  const request = { deliveryId: "a".repeat(32), action: "project_lifecycle" as const, projectId: branchId,
    operation: "start" as const, requestId: "branch-start" };
  return { root, main, branch, otherMain, otherBranch, registry, inventories, branchId, otherBranchId, instancesPath, supervisor,
    owner, nativeEffect, readInventory, mainRun, control, request, setBefore: (hook?: () => Promise<void>) => { beforeEffect = hook; },
    setFailure: (result: BranchLifecycleResult) => { nativeFailure = result; } };
}

describe("registered branch lifecycle through the native instance owner", () => {
  it("reads an offline non-current project's status without a native command or main-line queue", async () => {
    const f = await setup();
    expect(await f.control()({ deliveryId: f.request.deliveryId, projectId: f.otherBranchId, action: "project_status", operation: "status" }))
      .toMatchObject({ code: "status", accepted: true, status: { state: "stopped" } });
    expect(f.readInventory).toHaveBeenCalledWith(f.otherMain);
    expect(f.nativeEffect).not.toHaveBeenCalled(); expect(f.mainRun).not.toHaveBeenCalled();
  });

  it.each(["start", "stop", "restart"] as const)("controls only the explicitly registered branch for %s", async operation => {
    const f = await setup(), control = f.control();
    expect(await control({ ...f.request, projectId: f.otherBranchId, operation })).toMatchObject({ state: "completed", accepted: true });
    expect(f.nativeEffect).toHaveBeenCalledWith(f.otherBranch, operation);
    expect(f.mainRun).not.toHaveBeenCalled();
    const registry = await readRegistry(f.instancesPath);
    expect(registry.instances["worktree:two"].projectRoot).toBe(f.otherBranch);
    expect(registry.instances["worktree:one"]).toBeUndefined();
    expect(registry.instances.main).toBeUndefined();
  });

  it("reserves concurrent duplicate requests once and recreates only receipt readers after ACK loss", async () => {
    const f = await setup(), entered = defer(), release = defer();
    f.setBefore(async () => { entered.release(); await release.promise; });
    const pending = f.control()(f.request);
    await entered.promise;
    expect(await f.control()(f.request)).toMatchObject({ state: "unknown" });
    release.release();
    await pending; // Simulate the caller losing this acknowledgement.
    expect(await f.control()(f.request)).toMatchObject({ state: "completed", accepted: true });
    expect(await f.control()({ ...f.request, action: "project_lifecycle_receipt" })).toMatchObject({ state: "completed" });
    expect(f.nativeEffect).toHaveBeenCalledTimes(1);
    const row = await new AssistantProjectLifecycleRequestStore({ directory: join(f.root, "requests") }).get(f.request.requestId);
    expect(row?.command).toMatchObject({ owner: "branch", instanceId: "worktree:one" });
    const proof = JSON.parse(readFileSync(branchCommandResultPath(row!.binding!.runtimeManagerDir, row!.command!.commandId), "utf8"));
    expect(proof).toMatchObject({ source: "electron_branch", workspaceRoot: f.branch, commandId: row!.command!.commandId });
  });

  it("refuses an occupied native lane without superseding it and permits an unrelated branch", async () => {
    const f = await setup(), current = f.supervisor.beginIntent({ instanceId: "worktree:one", operation: "restart", desiredState: "open" });
    expect(await f.control()(f.request)).toMatchObject({ state: "rejected" });
    expect(f.supervisor.isCurrent(current)).toBe(true);
    expect(await f.control()({ ...f.request, projectId: f.otherBranchId, requestId: "unrelated" })).toMatchObject({ state: "completed" });
    expect(f.nativeEffect).toHaveBeenCalledTimes(1);
    expect(f.nativeEffect).toHaveBeenCalledWith(f.otherBranch, "start");
  });

  it("does not cross a revoked registration while the original request is waiting", async () => {
    const f = await setup(), entered = defer(), release = defer();
    f.setBefore(async () => { entered.release(); await release.promise; });
    const pending = f.control()(f.request);
    await entered.promise;
    await f.registry.reconcile({ schemaVersion: 1, integrationRoot: f.main, items: [{ id: "main", path: f.main, checkedOut: true }] });
    release.release();
    expect(await pending).toMatchObject({ state: "rejected", code: "registration_changed" });
    expect(f.nativeEffect).not.toHaveBeenCalled();
    expect(await f.control()(f.request)).toMatchObject({ state: "rejected", code: "project_unavailable" });
  });

  it("keeps unknown native work uncertain across restart and never replays the same request", async () => {
    const f = await setup();
    f.setBefore(async () => { throw new Error("lost native result"); });
    expect(await f.control()(f.request)).toMatchObject({ state: "unknown" });
    expect(await f.control()(f.request)).toMatchObject({ state: "unknown" });
    expect(await f.control()({ ...f.request, action: "project_lifecycle_receipt" })).toMatchObject({ state: "unknown" });
    expect(f.nativeEffect).not.toHaveBeenCalled();
    const row = await new AssistantProjectLifecycleRequestStore({ directory: join(f.root, "requests") }).get(f.request.requestId);
    expect(row?.command?.owner).toBe("branch");
    expect(JSON.parse(readFileSync(branchCommandResultPath(row!.binding!.runtimeManagerDir, row!.command!.commandId), "utf8")).completed).toBe(false);
  });

  it("preserves native active-work refusal as a durable rejected receipt", async () => {
    const f = await setup();
    f.setFailure({ schemaVersion: 1, accepted: false, operation: "stop", code: "active_work_blocked" });
    const request = { ...f.request, operation: "stop" as const };
    expect(await f.control()(request)).toMatchObject({ state: "rejected", code: "active_work_blocked", accepted: false });
    expect(await f.control()(request)).toMatchObject({ state: "rejected", code: "active_work_blocked" });
    expect(f.nativeEffect).not.toHaveBeenCalled();
  });

  it("rejects native proof replacement or foreign branch identity instead of reporting completion", async () => {
    const f = await setup();
    await f.control()(f.request);
    const row = await new AssistantProjectLifecycleRequestStore({ directory: join(f.root, "requests") }).get(f.request.requestId);
    const path = branchCommandResultPath(row!.binding!.runtimeManagerDir, row!.command!.commandId);
    const record = JSON.parse(readFileSync(path, "utf8")); record.workspaceRoot = f.otherBranch;
    writeFileSync(path, JSON.stringify(record));
    expect(await f.control()(f.request)).toMatchObject({ state: "unknown" });
    expect(f.nativeEffect).toHaveBeenCalledTimes(1);
  });

  it("rejects cross-repository native instance collisions inside the registry lock", async () => {
    const f = await setup();
    const first = await claimStart(f.instancesPath, { instanceId: "worktree:shared", projectRoot: f.branch,
      expectedProjectRoot: f.branch, operation: "start", commandId: "first-native", deadlineAt: new Date(Date.now() + 60000).toISOString(),
      ownerPid: process.pid, portIsFree: () => true });
    expect(first.ok).toBe(true);
    const original = readFileSync(f.instancesPath, "utf8");
    await expect(claimStop(f.instancesPath, { instanceId: "worktree:shared", projectRoot: f.otherBranch,
      expectedProjectRoot: f.otherBranch, commandId: "foreign-stop" })).rejects.toThrow("INSTANCE_PROJECT_ROOT_MISMATCH");
    await expect(claimStart(f.instancesPath, { instanceId: "worktree:shared", projectRoot: f.otherBranch,
      expectedProjectRoot: f.otherBranch, operation: "restart", commandId: "foreign-start", deadlineAt: new Date(Date.now() + 60000).toISOString(),
      ownerPid: process.pid, portIsFree: () => true })).rejects.toThrow("INSTANCE_PROJECT_ROOT_MISMATCH");
    expect(readFileSync(f.instancesPath, "utf8")).toBe(original);
    const stop = vi.fn();
    await expect(retireIsolatedRuntimeBeforeStart({ instanceId: "worktree:shared", workspaceRoot: f.otherBranch,
      expectedProjectRoot: f.otherBranch, registryPath: f.instancesPath, dependencies: { claimStopIfGeneration: stop } }))
      .rejects.toThrow("INSTANCE_PROJECT_ROOT_MISMATCH");
    expect(stop).not.toHaveBeenCalled();
  });

  it.skipIf(process.platform !== "win32")("uses the windowless read-only bridge for a non-current registered integration root", async () => {
    const f = await setup();
    const source = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
    const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => !key.toUpperCase().startsWith("GIT_")));
    const common = execFileSync("git", ["rev-parse", "--path-format=absolute", "--git-common-dir"], { cwd: source, env, encoding: "utf8", windowsHide: true }).trim();
    const python = join(dirname(common), ".venv", "Scripts", "pythonw.exe");
    expect(existsSync(python)).toBe(true);
    mkdirSync(join(f.otherMain, "scripts"));
    writeFileSync(join(f.otherMain, "scripts", "vibelution_desktop_entry.py"), [
      "import json, sys", "a = sys.argv", "def arg(k): return a[a.index(k)+1]",
      "assert arg('--action') == 'launcher-api'", "assert arg('--launcher-api-path') == 'branch-instances'",
      "assert arg('--launcher-api-method') == 'GET'", "assert '--no-browser' in a",
      "print(json.dumps({'ok': True, 'payload': {'schemaVersion': 1, 'integrationRoot': arg('--workspace'), 'items': []}}))",
    ].join("\n"));
    const payload = await readNativeBranchInstanceInventory({ integrationRoot: f.otherMain, pythonPath: python, operatorConfigPath: join(f.root, "operator.toml") });
    expect(payload).toMatchObject({ integrationRoot: f.otherMain, items: [] });
    expect(f.nativeEffect).not.toHaveBeenCalled();
  }, 20000);
});
