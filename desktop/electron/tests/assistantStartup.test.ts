import { existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { runInNewContext } from "node:vm";
import { createSourceFile, isCallExpression, isExpressionStatement, isFunctionDeclaration, isNewExpression, isVariableStatement, ScriptTarget, transpileModule } from "typescript";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AssistantProjectRegistryConnection } from "../src/assistant/projectRegistryConnection.js";
import { PrehostRecoveryDrainedUnknown } from "../src/assistant/prehostRecoveryJob.js";
import { InitialMigrationResults } from "../src/assistant/initialMigrationResults.js";
import { startAssistantReminderPump } from "../src/assistant/reminderPump.js";
import { AssistantProjectLifecycleRequestStore } from "../src/assistant/projectLifecycleRequestStore.js";
import { unwrapSource } from "../src/state/launcherStateStore.js";
import { createSingleInstanceEnvelope, resolveSecondInstanceIntent, resolveSingleInstanceCliIntent, resolveSingleInstanceProvenance } from "../src/appLock.js";
import { parseDesktopCliArgs } from "../src/cli/desktopCli.js";
import { applyDesktopLaunchSettingsToEnvironment, resolveDesktopLaunchSettings } from "../src/launch/desktopLaunchSettings.js";
import { planProjectSlot, projectSlotWindowAction } from "../src/protocol/applyProjectSlot.js";
import { parseBranchInstanceRecords } from "../src/protocol/launcherControlClient.js";
import { ProjectAdmission, registeredInstancesForPhysicalRoot } from "../src/lifecycle/projectAdmission.js";
import { startManagedLegacyReminderRetirement } from "../src/notifications/managedLegacyReminderRetirement.js";

const ownedRoots: string[] = [];
afterEach(() => { for (const root of ownedRoots.splice(0)) rmSync(root, { recursive: true, force: true }); });

const source = readFileSync(new URL("../src/main.ts", import.meta.url), "utf8");
const ast = createSourceFile("main.ts", source, ScriptTarget.Latest, true);
const declarations = ["startLauncherAssistant", "stopLauncherAssistant"].map(name => {
  const fn = ast.statements.find(node => isFunctionDeclaration(node) && node.name?.text === name);
  if (!fn) throw new Error(`Missing ${name}`);
  return fn.getFullText(ast);
}).join("\n");
const assistantOpenDeclaration = ast.statements.find(node => isFunctionDeclaration(node)
  && node.name?.text === "requestOpenAssistantFromSecondInstance")?.getFullText(ast) ?? "";
const secondInstanceRegistration = ast.statements.find(node => isExpressionStatement(node)
  && isCallExpression(node.expression) && node.expression.expression.getText(ast) === "app.on"
  && node.expression.arguments[0]?.getText(ast) === '"second-instance"')?.getFullText(ast);
if (!secondInstanceRegistration) throw new Error("Missing second-instance handler");
const stateStore = ast.statements.filter(isVariableStatement).flatMap(node => [...node.declarationList.declarations])
  .find(node => node.name.getText(ast) === "launcherStateStore")?.initializer;
if (!stateStore || !isNewExpression(stateStore) || !stateStore.arguments?.[0]) throw new Error("Missing Launcher state refresh callback");
const stateRefresh = stateStore.arguments[0].getFullText(ast);

function fixture() {
  const host = { start: vi.fn(async () => undefined), stop: vi.fn(async () => undefined) };
  const window = { open: vi.fn(async () => undefined) };
  const projectSnapshot = { schemaVersion: 1, revision: 0, projects: {} };
  let pendingStart: Promise<unknown> = Promise.resolve();
  const projects = {
    snapshot: vi.fn(() => projectSnapshot),
    hasPendingPreHostRecovery: vi.fn(() => false),
    pendingPreHostRecovery: vi.fn(() => null as { projectId: string; operationId: string } | null),
    recoverPreHostSource: vi.fn(async (_operationId: string, _acquire: (marker: unknown) => Promise<unknown>) => false),
    revokePreHostRecovery: vi.fn(),
    start: vi.fn(async (createHost: (snapshot: unknown, suspended: boolean) => typeof host, options?: { migration?: boolean }) => {
      const result = createHost(projectSnapshot, projects.hasPendingPreHostRecovery());
      const migrating = result as typeof host & { startForMigration?: () => Promise<unknown> };
      pendingStart = options?.migration && migrating.startForMigration ? migrating.startForMigration() : result.start();
      await pendingStart; return result;
    }),
    stop: vi.fn(async () => { await pendingStart.catch(() => undefined); await host.stop(); }),
  };
  const context: Record<string, any> = {
    launcherAssistantStarting: null, launcherAssistantStopping: null, initialMigrationReceiptFence: null, launcherAssistantStartupAbort: new AbortController(),
    launcherAssistantHost: null, launcherAssistantWindow: null, showAssistantStartupWait: null, dismissAssistantStartupWait: null, flushAssistantMigrationFeedback: null, assistantMigrationPending: false,
    launcherAssistantProjects: null, stopLauncherAssistantReminders: null, pendingAssistantOpen: null,
    projectAdmissionExperiment: false,
    projectAdmission: null, legacyReminderAdmission: null,
    launcherAssistantExitReady: false, desktopTray: null, assistantOnly: true, shutdownApproved: false,
    app: { isPackaged: true, quit: vi.fn(), on: vi.fn(), getPath: vi.fn(() => "private") }, join, console,
    AbortController, PrehostRecoveryDrainedUnknown, setTimeout, clearTimeout, dialog: { showMessageBox: vi.fn(async () => ({ response: 0 })) },
    BrowserWindow: { getAllWindows: vi.fn(() => []) },
    desktopCliArgs: { hiddenPresentation: true }, desktopPythonPath: vi.fn(() => ""),
    desktopEnvironment: () => ({ VIBELUTION_CONFIG_PATH: "private-config" }),
    desktopLaunchSettings: () => ({ configPath: "private-config" }),
    process: { env: {}, resourcesPath: "resources" },
    createAssistantProjectMainControl: vi.fn(() => async () => ({ state: "unknown" })),
    createAssistantAppearanceMainControl: vi.fn(() => async () => ({ code: "unavailable" })),
    existingMainLineCommandQueueForProject: vi.fn(() => undefined),
    withProjectAdmission: async (_root: () => string, work: () => Promise<unknown>) => work(),
    resolveAssistantResources: vi.fn(async () => ({ sourceRoot: "sealed-source", pythonPath: "sealed-pythonw",
      pythonArguments: ["-I"], env: { VIBELUTION_CONFIG_PATH: "private-config" } })),
    readProjectId: vi.fn(() => "p"), instanceIdForProject: vi.fn(() => "i"),
    AssistantHost: vi.fn(function () { return host; }), AssistantWindow: vi.fn(function () { return window; }),
    AssistantProjectLifecycleRequestStore: vi.fn(function () { return { get: vi.fn(async () => null) }; }),
    startAssistantReminderPump: vi.fn(() => vi.fn(async () => undefined)),
    AssistantProjectRegistryConnection: vi.fn(function () { return projects; }),
    createAssistantTray: vi.fn(() => ({ destroy: vi.fn() })), requestDesktopShellExit: vi.fn(),
    requestOpenLauncherFromAssistant: vi.fn(async () => ({ opened: true })),
    resolveSingleInstanceProvenance, resolveSingleInstanceCliIntent, resolveSecondInstanceIntent,
    findVibelutionDeepLinkArg: vi.fn(() => null), handlePublicDeepLinkUrl: vi.fn(),
    applyPendingProjectSlot: vi.fn(), handleSecondInstanceLifecycleCommand: vi.fn(),
    requestOpenWorkbenchFromSecondInstance: vi.fn(), focusExistingDesktopShell: vi.fn(),
  };
  runInNewContext(transpileModule(`${declarations}\n${assistantOpenDeclaration}\n${secondInstanceRegistration}\nglobalThis.start=startLauncherAssistant;globalThis.stop=stopLauncherAssistant;`, {
    compilerOptions: { target: ScriptTarget.ES2022 },
  }).outputText, context);
  return { context, host, window, projects, projectSnapshot, paths: { resourcesRoot: "resources", workspaceRoot: "", userDataRoot: "private", desktopBundleRoot: "bundle" } };
}

function projectEntryFixture() {
  const value = fixture();
  const { context, paths } = value;
  const receipt = { duplicate: false, failed: vi.fn(), dispatched: vi.fn() };
  const initialSettings = { assistant: true, workspaceRoot: "", configPath: "private-config", pythonPath: "" };
  Object.assign(context, {
    projectControlPlaneStartup: null, projectControlPlaneLaunchSettings: null,
    projectControlPlaneAutomaticLifecycle: true,
    windowProvider: null, launcherBootstrap: null, pendingProjectRoot: "",
    launcherControlPlaneReady: Promise.resolve(),
    desktopLaunchSettings: () => context.projectControlPlaneLaunchSettings || initialSettings,
    resolveDeferredProjectLaunchSettings: vi.fn((_input, projectRoot) => ({
      schemaVersion: 1, workspaceRoot: projectRoot || "registered-project", configPath: "private-config", pythonPath: "project-python",
    })),
    createDesktopPathsForApp: vi.fn(() => {
      if (!context.projectControlPlaneLaunchSettings?.workspaceRoot) throw new Error("project paths before binding");
      return { ...paths, workspaceRoot: context.projectControlPlaneLaunchSettings.workspaceRoot };
    }),
    claimElectronDesktopShellOwner: vi.fn(),
    releaseElectronDesktopShellOwner: vi.fn(),
    bootstrapProjectControlPlane: vi.fn(async () => { context.launcherBootstrap = {}; context.windowProvider = {}; }),
    startProjectControlPlaneObservers: vi.fn(),
    beginLaunchRequestReceipt: vi.fn(() => receipt),
    PROJECT_SLOT_LIFECYCLE_COMMANDS: new Set(["start", "stop", "restart"]),
    normalizeInstanceKey: (root: string) => root,
    orchestrateLauncherLifecycle: vi.fn(async () => ({ accepted: true })),
    notifyDesktopTray: vi.fn(), process: { env: {}, resourcesPath: "resources" },
  });
  context.app.whenReady = vi.fn(async () => undefined);
  const functions = ["ensureProjectControlPlane", "applyPendingProjectSlot", "applyPendingProjectSlotImpl"].map(name =>
    ast.statements.find(node => isFunctionDeclaration(node) && node.name?.text === name)?.getFullText(ast) || "").join("\n");
  runInNewContext(transpileModule(`${functions}\nglobalThis.ensureProject=typeof ensureProjectControlPlane === 'undefined' ? undefined : ensureProjectControlPlane;`, {
    compilerOptions: { target: ScriptTarget.ES2022 },
  }).outputText, context);
  return { ...value, receipt };
}

describe("resident assistant followed by an ordinary project entry", () => {
  it("attaches management without stopping live projects or restoring old restart requests", async () => {
    const { context, paths } = projectEntryFixture();
    const forbidden = ["reapManagedRuntimeOnDesktopStart", "reclaimExpiredIsolatedStops",
      "startPeriodicShellFreshnessWatch", "startWorkbenchBackendWatchdogLoop", "maybeRestoreTrayRestartAllPending"];
    Object.assign(context, {
      AbortController, performance, electronStartupStage: "", resolveLauncherControlPlaneReady: null,
      resolveInitialWorkbenchUrl: vi.fn(async () => ""),
      registerPackagedDeepLinks: vi.fn(() => ({ attempted: false, registered: false, reason: "private" })),
      bootstrapMainOwnedLauncher: vi.fn(async () => ({ mode: "main_orchestrated", launcherBackendPid: 0 })),
      createWindowProvider: vi.fn(() => ({})), updateLauncherWindowTruth: vi.fn(),
      electronStartupFields: vi.fn((fields: unknown) => fields), electronStageElapsedMs: vi.fn(() => 0),
      createDesktopTray: vi.fn(() => ({})), scheduleTelemetryWithoutWaiting: vi.fn(),
      startDeferredRestartFulfillment: vi.fn(),
      ...Object.fromEntries(forbidden.map(name => [name, vi.fn()])),
    });
    const bootstrap = ast.statements.find(node => isFunctionDeclaration(node) && node.name?.text === "bootstrapProjectControlPlane")!.getFullText(ast);
    runInNewContext(transpileModule(bootstrap, { compilerOptions: { target: ScriptTarget.ES2022 } }).outputText, context);
    await expect(context.ensureProject("human-project", true)).resolves.toBe(true);
    for (const name of forbidden) expect(context[name], name).not.toHaveBeenCalled();
    expect(context.createWindowProvider).toHaveBeenCalledOnce();
    expect(context.projectControlPlaneAutomaticLifecycle).toBe(false);
    expect(Number.isFinite(context.projectControlPlaneRecoveryNotBefore)).toBe(true);
    expect(context.startDeferredRestartFulfillment).toHaveBeenCalledOnce();
    // Subsequent observer/status refreshes must not mutate an expired registry.
    context.reconcileOrphanedInstanceRegistry = vi.fn();
    const reclaim = ast.statements.find(node => isFunctionDeclaration(node) && node.name?.text === "reclaimExpiredIsolatedStops")!.getFullText(ast);
    runInNewContext(transpileModule(reclaim, { compilerOptions: { target: ScriptTarget.ES2022 } }).outputText, context);
    await context.reclaimExpiredIsolatedStops();
    expect(context.reconcileOrphanedInstanceRegistry).not.toHaveBeenCalled();
    expect(paths.workspaceRoot).toBe("");
  });
  it("releases only the failed deferred context and permits a different human project selection", async () => {
    const { context, host, paths } = projectEntryFixture();
    await context.start(paths);
    context.bootstrapProjectControlPlane.mockRejectedValueOnce(new Error("unavailable project"));
    await expect(context.ensureProject("unavailable-project")).rejects.toThrow("unavailable project");
    expect(context.releaseElectronDesktopShellOwner).toHaveBeenCalledExactlyOnceWith("unavailable-project");
    expect(context.projectControlPlaneLaunchSettings).toBeNull();
    expect(context.projectControlPlaneStartup).toBeNull();
    await expect(context.ensureProject("available-project")).resolves.toBe(true);
    expect(context.projectControlPlaneLaunchSettings.workspaceRoot).toBe("available-project");
    expect(context.claimElectronDesktopShellOwner.mock.calls).toEqual([["unavailable-project"], ["available-project"]]);
    expect(host.start).toHaveBeenCalledOnce(); expect(host.stop).not.toHaveBeenCalled();
  });
  it("initializes the existing project control plane and dispatches without restarting the assistant", async () => {
    const { context, host, paths, receipt } = projectEntryFixture();
    await context.start(paths);
    await expect(context.applyPendingProjectSlot("project-a", "start", "operator", { workspaceRoot: "project-a" })).resolves.toBeUndefined();
    expect(context.bootstrapProjectControlPlane).toHaveBeenCalledTimes(1);
    expect(context.orchestrateLauncherLifecycle).toHaveBeenCalledWith("start", { schemaVersion: 1, path: "project-slot" }, "operator");
    expect(receipt.dispatched).toHaveBeenCalledOnce();
    expect(host.start).toHaveBeenCalledOnce(); expect(host.stop).not.toHaveBeenCalled();
    expect(context.assistantOnly).toBe(false);
  });

  it("retains the native integration workspace and sends a worktree slot through its existing supervisor", async () => {
    const { context, host, paths, receipt } = projectEntryFixture();
    await context.start(paths);
    const integrationRoot = "C:/repo";
    const worktreeRoot = "C:/repo/.worktrees/task";
    const listed = { items: [
      { id: "main", path: integrationRoot, kind: "main", current: true, alive: true, checkedOut: true, port: 8000 },
      { id: "worktree:task", path: worktreeRoot, kind: "worktree", current: false, alive: false, checkedOut: true, port: 8001 },
    ] };
    Object.assign(context, {
      launcherStateStore: { refresh: vi.fn(async () => undefined), projectBranchInstances: () => listed },
      parseBranchInstanceRecords, planProjectSlot, projectSlotWindowAction,
      orchestrateBranchInstanceLifecycle: vi.fn(async () => ({ accepted: true })),
    });
    const handler = context.app.on.mock.calls.find(([name]: [string]) => name === "second-instance")[1];
    handler(undefined, [], "", createSingleInstanceEnvelope({ workspaceRoot: integrationRoot, projectRoot: worktreeRoot, lifecycleCommand: "start" }));
    await vi.waitFor(() => expect(receipt.dispatched).toHaveBeenCalledOnce());
    expect(context.projectControlPlaneLaunchSettings.workspaceRoot).toBe(integrationRoot);
    expect(context.orchestrateLauncherLifecycle).not.toHaveBeenCalled();
    expect(context.orchestrateBranchInstanceLifecycle).toHaveBeenCalledWith("start", {
      schemaVersion: 1, path: "branch-instances/start", init: { method: "POST", body: { instanceId: "worktree:task" } },
    }, "operator");
    expect(receipt.dispatched).toHaveBeenCalledOnce(); expect(host.stop).not.toHaveBeenCalled();
  });

  it("shares initialization across concurrent same or different project requests", async () => {
    const { context, host, paths } = projectEntryFixture();
    await context.start(paths);
    let release!: () => void;
    context.bootstrapProjectControlPlane.mockImplementation(async () => {
      await new Promise<void>(resolve => { release = resolve; });
      context.launcherBootstrap = {}; context.windowProvider = {};
    });
    const first = context.ensureProject("project-a");
    const same = context.ensureProject("project-a");
    const other = context.ensureProject("project-b");
    await vi.waitFor(() => expect(context.bootstrapProjectControlPlane).toHaveBeenCalledOnce());
    release(); await Promise.all([first, same, other]);
    await context.ensureProject("project-a");
    expect(context.resolveDeferredProjectLaunchSettings).toHaveBeenCalledOnce();
    expect(context.createDesktopPathsForApp).toHaveBeenCalledOnce();
    expect(context.startProjectControlPlaneObservers).not.toHaveBeenCalled();
    expect(host.stop).not.toHaveBeenCalled();
  });

  it("contains project initialization failure and leaves the assistant alive", async () => {
    const { context, host, paths, receipt } = projectEntryFixture();
    await context.start(paths);
    context.bootstrapProjectControlPlane.mockRejectedValueOnce(new Error("project unavailable"));
    await expect(context.applyPendingProjectSlot("project-a", "start", "operator")).resolves.toBeUndefined();
    expect(context.notifyDesktopTray).toHaveBeenCalled();
    expect(receipt.dispatched).not.toHaveBeenCalled();
    expect(context.assistantOnly).toBe(true); expect(host.stop).not.toHaveBeenCalled();
    expect(context.app.quit).not.toHaveBeenCalled();
  });
});

describe("resident assistant startup", () => {
  it("uses a fresh inventory and one sealed verifier for the original recovery ID before starting the host", async () => {
    const { context, projects, paths } = fixture();
    const operationId = "initial-" + "b".repeat(40), projectId = "project";
    const marker = { projectId, operationId, registration: { root: "source-root" } };
    const signal = new AbortController().signal;
    const seal = { signal, check: vi.fn(), drain: vi.fn(async () => {}), release: vi.fn() };
    const worker = { check: vi.fn(async () => true), verifyReceipt: vi.fn(async () => true),
      commitMarker: vi.fn(async () => true), release: vi.fn(async () => {}) };
    projects.hasPendingPreHostRecovery.mockReturnValue(true);
    projects.pendingPreHostRecovery.mockReturnValue({ projectId, operationId });
    projects.recoverPreHostSource.mockImplementation(async (id, acquire) => {
      expect(id).toBe(operationId);
      expect(context.launcherStateStore.refresh).toHaveBeenCalledOnce();
      const lease = await acquire(marker) as typeof worker;
      expect(lease).toBeTruthy(); await lease.release(); return false;
    });
    context.launcherStateStore = { refresh: vi.fn(async () => ({})) };
    context.projectAdmission = { seal: vi.fn(() => seal) };
    context.resolveProjectsHome = () => "source-projects";
    context.startPrehostRecoveryJob = vi.fn(async () => worker);
    await context.start(paths);
    expect(context.startPrehostRecoveryJob).toHaveBeenCalledWith(expect.objectContaining({ marker, projectSeal: seal, sourceProjectsHome: "source-projects" }));
    expect(worker.release).toHaveBeenCalledOnce();
    expect(seal.release).toHaveBeenCalledOnce();
    expect(projects.start).toHaveBeenCalledOnce();
    await context.stop();
  });

  it("forwards a source admission revoke to the registry before releasing the original verifier", async () => {
    const { context, projects, paths } = fixture();
    const operationId = "initial-" + "e".repeat(40), projectId = "project", abort = new AbortController();
    const marker = { projectId, operationId, registration: { root: "source-root" } };
    const seal = { signal: abort.signal, check: vi.fn(), drain: vi.fn(async () => {}), release: vi.fn() };
    const worker = { check: vi.fn(async () => true), verifyReceipt: vi.fn(async () => true),
      commitMarker: vi.fn(async () => true), release: vi.fn(async () => {}) };
    projects.hasPendingPreHostRecovery.mockReturnValue(true);
    projects.pendingPreHostRecovery.mockReturnValue({ projectId, operationId });
    projects.recoverPreHostSource.mockImplementation(async (_id, acquire) => {
      const lease = await acquire(marker) as typeof worker;
      abort.abort(); expect(projects.revokePreHostRecovery).toHaveBeenCalledOnce();
      await lease.release(); return false;
    });
    context.launcherStateStore = { refresh: vi.fn(async () => ({})) };
    context.projectAdmission = { seal: vi.fn(() => seal) };
    context.resolveProjectsHome = () => "source-projects";
    context.startPrehostRecoveryJob = vi.fn(async () => worker);
    await context.start(paths);
    expect(worker.release).toHaveBeenCalledOnce();
    expect(seal.release).toHaveBeenCalledOnce();
    await context.stop();
  });

  it("retains source admission if verifier startup leaves output drain unknown", async () => {
    const { context, projects, paths } = fixture();
    const operationId = "initial-" + "c".repeat(40), projectId = "project";
    const marker = { projectId, operationId, registration: { root: "source-root" } };
    const seal = { signal: new AbortController().signal, check: vi.fn(), drain: vi.fn(async () => {}), release: vi.fn() };
    projects.hasPendingPreHostRecovery.mockReturnValue(true);
    projects.pendingPreHostRecovery.mockReturnValue({ projectId, operationId });
    projects.recoverPreHostSource.mockImplementation(async (_id, acquire) => { expect(await acquire(marker)).toBeNull(); return false; });
    context.launcherStateStore = { refresh: vi.fn(async () => ({})) };
    context.projectAdmission = { seal: vi.fn(() => seal) };
    context.resolveProjectsHome = () => "source-projects";
    context.startPrehostRecoveryJob = vi.fn(async () => { throw new Error("PREHOST_RECOVERY_DRAIN_UNKNOWN"); });
    await context.start(paths);
    expect(seal.release).not.toHaveBeenCalled();
    await context.stop();
  });

  it("releases admission after a confirmed Job drain with unknown result while retaining recovery", async () => {
    const { context, projects, paths } = fixture();
    const operationId = "initial-" + "d".repeat(40), projectId = "project";
    const marker = { projectId, operationId, registration: { root: "source-root" } };
    const seal = { signal: new AbortController().signal, check: vi.fn(), drain: vi.fn(async () => {}), release: vi.fn() };
    projects.hasPendingPreHostRecovery.mockReturnValue(true);
    projects.pendingPreHostRecovery.mockReturnValue({ projectId, operationId });
    projects.recoverPreHostSource.mockImplementation(async (_id, acquire) => { expect(await acquire(marker)).toBeNull(); return false; });
    context.launcherStateStore = { refresh: vi.fn(async () => ({})) };
    context.projectAdmission = { seal: vi.fn(() => seal) };
    context.resolveProjectsHome = () => "source-projects";
    context.startPrehostRecoveryJob = vi.fn(async () => { throw new PrehostRecoveryDrainedUnknown(); });
    await context.start(paths);
    expect(seal.release).toHaveBeenCalledOnce();
    expect(projects.pendingPreHostRecovery()).toEqual({ projectId, operationId });
    await context.stop();
  });

  it("shows a surviving recovery receipt when a hidden assistant is opened", async () => {
    const { context, projects, paths } = fixture();
    const operationId = "affairs-" + "a".repeat(40);
    projects.hasPendingPreHostRecovery.mockReturnValue(true);
    projects.pendingPreHostRecovery.mockReturnValue({ projectId: "project", operationId });
    await context.start(paths);
    expect(context.dialog.showMessageBox).not.toHaveBeenCalled();
    context.pendingAssistantOpen = { show: true };
    context.flushAssistantMigrationFeedback();
    expect(context.dialog.showMessageBox).toHaveBeenCalledWith(expect.objectContaining({
      detail: expect.stringContaining(operationId),
    }));
    await context.stop();
  });

  it("passes an approved episodic conflict resolution through the registered project lease", async () => {
    const { context, host, paths } = fixture();
    const sync = vi.fn(async () => ({ state: "resolved" }));
    Object.assign(host, { syncEpisodic: sync });
    await context.start(paths);
    context.launcherAssistantProjects.withHistoryImport = vi.fn(async (_id: string, work: (revision: number) => Promise<unknown>) => work(7));
    const control = context.AssistantHost.mock.calls[0][0].mainControl;
    const request = { action: "episodic_sync", projectId: "project:one", previewId: "a".repeat(64),
      turnId: "turn-one", resolveSyncId: "episodic-" + "b".repeat(40), reviewToken: "c".repeat(64) };
    const signal = new AbortController().signal;
    await control(request, signal);
    expect(context.launcherAssistantProjects.withHistoryImport).toHaveBeenCalledWith(request.projectId, expect.any(Function));
    expect(sync).toHaveBeenCalledWith({ projectId: request.projectId, previewId: request.previewId,
      turnId: request.turnId, revision: 7, signal, resolveSyncId: request.resolveSyncId, reviewToken: request.reviewToken });
  });
  it("rejects a first assistant/deep-link launch before requesting the primary lock", () => {
    const declarations = ast.statements.filter(isVariableStatement);
    const named = (name: string) => declarations.find(statement => statement.declarationList.declarations
      .some(declaration => declaration.name.getText(ast) === name));
    const parse = named("desktopCliArgs");
    const lock = named("lockDecision");
    expect(parse).toBeTruthy(); expect(lock).toBeTruthy();
    expect(parse!.pos).toBeLessThan(lock!.pos);
    const context = {
      desktopLaunchArgv: ["--assistant", "vibelution://open?project=old"], parseDesktopCliArgs,
      app: { exit: vi.fn(), requestSingleInstanceLock: vi.fn(() => true) },
      console: { warn: vi.fn() }, singleInstanceEnvelope: {}, singleInstanceDecision: vi.fn(),
    };
    const execute = () => runInNewContext(transpileModule(`${parse!.getFullText(ast)}\n${lock!.getFullText(ast)}`, {
      compilerOptions: { target: ScriptTarget.ES2022 },
    }).outputText, context);
    expect(execute).toThrow("ASSISTANT_MODE_CONFLICT");
    expect(context.app.exit).toHaveBeenCalledExactlyOnceWith(1);
    expect(context.app.requestSingleInstanceLock).not.toHaveBeenCalled();
  });

  it("takes the no-workspace startup path despite persisted and inherited project bindings", async () => {
    const { context, host } = fixture();
    const cliArgs = parseDesktopCliArgs(["--assistant", "--hidden-presentation"]);
    const inherited = { VIBELUTION_WORKSPACE_ROOT: "old-checkout", VIBELUTION_PYTHON_PATH: "old-python" };
    const settings = resolveDesktopLaunchSettings({ env: inherited, cliArgs, userDataRoot: "private", resourcesRoot: "resources",
      readTextFile: () => JSON.stringify({ workspaceRoot: "persisted-checkout", pythonPath: "persisted-python", operatorConfigPath: "private-config" }),
      fileExists: () => { throw new Error("project Python probe"); } });
    Object.assign(context, { desktopCliArgs: cliArgs,
      desktopEnvironment: () => applyDesktopLaunchSettingsToEnvironment(inherited, settings),
      process: { env: {}, resourcesPath: "resources" }, resolveDesktopBundleRoot: vi.fn(() => "sealed-bundle"),
      createDesktopPathsForApp: vi.fn(() => { throw new Error("project paths must not be created"); }),
      claimElectronDesktopShellOwner: vi.fn(), localDebuggingEnabled: false,
      registerLauncherAppProtocolHandle: vi.fn(), resolveLauncherDistRoot: vi.fn(),
      resolveLauncherControlPlaneReady: vi.fn(),
    });
    const begin = source.indexOf("const workspaceRoot = String(desktopEnvironment()");
    const end = source.indexOf("    if (!await ensureProjectControlPlane(workspaceRoot)) return;", begin);
    expect(begin).toBeGreaterThan(-1); expect(end).toBeGreaterThan(begin);
    const startup = source.slice(begin, end).replaceAll("import.meta.url", '"file:///sealed/main.js"');
    await runInNewContext(transpileModule(`(async () => { ${startup} })()`, {
      compilerOptions: { target: ScriptTarget.ES2022 },
    }).outputText, context);
    expect(context.assistantOnly).toBe(true);
    expect(context.createDesktopPathsForApp).not.toHaveBeenCalled();
    expect(context.claimElectronDesktopShellOwner).not.toHaveBeenCalled();
    expect(context.desktopPythonPath).not.toHaveBeenCalled();
    expect(host.start).toHaveBeenCalledTimes(1);
  });

  it("carries the explicit assistant intent in main's actual lock envelope", () => {
    const declaration = ast.statements.filter(isVariableStatement).flatMap(node => [...node.declarationList.declarations])
      .find(node => node.name.getText(ast) === "singleInstanceEnvelope")?.initializer;
    expect(declaration).toBeTruthy();
    const context = { createSingleInstanceEnvelope, desktopCliArgs: parseDesktopCliArgs(["--assistant"]),
      desktopLifecycleLaunchMetadata: { command: "", source: "", reason: "", stopManager: false, explicitlyForwarded: false },
      result: undefined as unknown };
    runInNewContext(transpileModule(`globalThis.result = ${declaration!.getText(ast)};`, {
      compilerOptions: { target: ScriptTarget.ES2022 },
    }).outputText, context);
    expect(context.result).toMatchObject({ assistant: true, projectRoot: "", openWorkbench: false });
  });

  it("keeps an explicit show request made before primary startup ahead of a later hidden request", async () => {
    const { context, window, paths } = fixture();
    const handler = context.app.on.mock.calls.find(([name]: [string]) => name === "second-instance")[1];
    handler(undefined, ["--assistant"], "", createSingleInstanceEnvelope({ assistant: true }));
    handler(undefined, ["--assistant", "--hidden-presentation"], "", createSingleInstanceEnvelope({ assistant: true, hiddenPresentation: true }));
    expect(context.AssistantHost).not.toHaveBeenCalled();
    await context.start(paths);
    expect(window.open).toHaveBeenCalledExactlyOnceWith({ show: true });
    expect(context.focusExistingDesktopShell).not.toHaveBeenCalled();
  });

  it("opens the same assistant on a project primary without focusing the shell or restarting the host", async () => {
    const { context, host, window, paths } = fixture();
    context.assistantOnly = false;
    await context.start({ ...paths, workspaceRoot: "existing-project" });
    const handler = context.app.on.mock.calls.find(([name]: [string]) => name === "second-instance")[1];
    handler(undefined, ["--assistant"], "", createSingleInstanceEnvelope({ assistant: true }));
    await vi.waitFor(() => expect(window.open).toHaveBeenCalledTimes(2));
    expect(window.open).toHaveBeenLastCalledWith({ show: true });
    expect(host.start).toHaveBeenCalledTimes(1);
    expect(context.focusExistingDesktopShell).not.toHaveBeenCalled();
    expect(context.applyPendingProjectSlot).not.toHaveBeenCalled();
    expect(context.requestOpenWorkbenchFromSecondInstance).not.toHaveBeenCalled();
  });

  it.each([false, true])("retains an assistant open before resource readiness and respects hidden=%s", async hiddenPresentation => {
    const { context, host, window, paths } = fixture();
    let release!: (value: unknown) => void;
    context.resolveAssistantResources.mockImplementation(() => new Promise(resolve => { release = resolve; }));
    const starting = context.start(paths);
    const handler = context.app.on.mock.calls.find(([name]: [string]) => name === "second-instance")[1];
    handler(undefined, ["--assistant"], "", createSingleInstanceEnvelope({ assistant: true, hiddenPresentation }));
    expect(host.start).not.toHaveBeenCalled();
    release({ sourceRoot: "sealed-source", pythonPath: "sealed-pythonw", pythonArguments: ["-I"], env: {} });
    await starting;
    expect(window.open).toHaveBeenCalledExactlyOnceWith({ show: !hiddenPresentation });
    expect(host.start).toHaveBeenCalledTimes(1);
    expect(context.focusExistingDesktopShell).not.toHaveBeenCalled();
  });

  it("starts with verified packaged resources and an empty authorized project registry", async () => {
    const { context, host, window, paths } = fixture();
    await context.start(paths);
    expect(context.readProjectId).not.toHaveBeenCalled();
    const options = context.AssistantHost.mock.calls[0][0];
    expect(options.projects).toEqual({});
    expect(options.projectSnapshot).toEqual({ schemaVersion: 1, revision: 0, projects: {} });
    expect(context.AssistantProjectRegistryConnection).toHaveBeenCalledWith(join("private", "assistant", "projects.json"));
    expect(options.sourceRoot).toBe("sealed-source");
    expect(options.pythonPath).toBe("sealed-pythonw");
    expect(options.pythonArguments).toEqual(["-I"]);
    expect(host.start).toHaveBeenCalledTimes(1);
    expect(window.open).toHaveBeenCalledWith({ show: false });
    await context.stop();
    expect(host.stop).toHaveBeenCalledTimes(1);
  });

  it("exposes the tray while recovery waits, and starts the host only after recovery ends", async () => {
    const { context, host, paths } = fixture();
    context.process.env.VIBELUTION_INITIAL_MIGRATION_EXPERIMENT = "1";
    context.InitialMigrationResults = vi.fn(function () { return {}; });
    context.verifyInitialMigrationResult = vi.fn();
    let finish!: (value: unknown[]) => void;
    context.recoverInitialMigrations = vi.fn(() => new Promise(resolve => { finish = resolve; }));
    const starting = context.start(paths);
    await vi.waitFor(() => expect(context.recoverInitialMigrations).toHaveBeenCalledOnce());
    expect(context.createAssistantTray).toHaveBeenCalledOnce();
    expect(context.AssistantHost).not.toHaveBeenCalled();
    const actions = context.createAssistantTray.mock.calls[0][1];
    actions.open();
    expect(context.dialog.showMessageBox).toHaveBeenCalledOnce();
    actions.openLauncher();
    expect(context.requestOpenLauncherFromAssistant).toHaveBeenCalledOnce();
    finish([]);
    await starting;
    expect(host.start).toHaveBeenCalledOnce();
  });

  it("enables initial migration without an environment opt-in", async () => {
    const { context, paths } = fixture();
    context.InitialMigrationResults = vi.fn(function () { return { get: vi.fn(async () => null) }; });
    context.recoverInitialMigrations = vi.fn(async () => []);
    context.verifyInitialMigrationResult = vi.fn();
    await context.start(paths);
    expect(context.recoverInitialMigrations).toHaveBeenCalledOnce();
    expect(context.AssistantHost.mock.calls[0][0].initialMigrationControl).toBe(true);
    await context.stop();
  });

  it("checks the original reminder handoff receipt when preparation is busy and preserves unknown", async () => {
    const { context, host, paths } = fixture();
    context.InitialMigrationResults = vi.fn(function () { return { get: vi.fn(async () => null) }; });
    context.recoverInitialMigrations = vi.fn(async () => []);
    context.verifyInitialMigrationResult = vi.fn();
    Object.assign(host, { prepareInitialMigration: vi.fn(async () => "busy"), reminderHandoffReceipt: vi.fn(async () => "pending") });
    await context.start(paths);
    const registry = context.launcherAssistantProjects;
    registry.withHistoryImport = vi.fn(async (_id: string, work: (revision: number) => Promise<unknown>) => work(0));
    const control = context.AssistantHost.mock.calls[0][0].mainControl;
    const request = { action: "initial_migration_queue", projectId: "project:one", previewId: "b".repeat(64),
      turnId: "turn", category: "reminder_handoff", operationId: "initial-" + "c".repeat(40), deliveryId: "d".repeat(32), timeoutMs: 10000 };
    const result = await control(request);
    expect(host.reminderHandoffReceipt).toHaveBeenCalledWith(request.projectId, 0);
    expect(result).toMatchObject({ operationId: request.operationId, state: "unknown", code: "unknown", readyForCutover: false });
    expect(context.recoverInitialMigrations).toHaveBeenCalledOnce();
    await context.stop();
  });

  it.each(["conflict", "unknown", "revoked", "slow", "busy", "failed_reopen", "barrier_crash", "retirement_crash"])("runs one %s handoff only after the original window and Job drain", async kind => {
    const { context, host, paths, projectSnapshot } = fixture();
    const root = mkdtempSync(join(tmpdir(), "handoff-main-")); ownedRoots.push(root);
    const physical = process.platform === "win32" ? realpathSync.native(root).toLowerCase() : realpathSync.native(root);
    paths.userDataRoot = root;
    const registryPath = join(root, "instances.json"), id = "project:one";
    const registryData = { instances: { source: { projectRoot: physical, spawnPid: 4242 } } };
    writeFileSync(registryPath, JSON.stringify(registryData));
    projectSnapshot.projects = { [id]: physical };
    const registration = { root: physical, baseProjectId: "project", registrationUuid: "fixture" };
    const row = { kind: "instance", instanceId: "source", windowId: 1, rendererProcessId: 11, ready: true };
    let closed = false, jobExited = false, closePending = false;
    const windowClose = vi.fn(async () => { throw new Error("must not automatically close"); });
    const provider = { completeWorkbenchWindowInventory: () => closed ? [] : [row],
      captureWorkbenchWindowRetirement: () => ({ isClosed: () => closed, close: windowClose }),
      hasPendingUserWorkbenchClose: () => closePending };
    const job = Object.assign(vi.fn(async () => jobExited), { pid: 4242, isCurrent: () => !jobExited, release: vi.fn() });
    const admission = new ProjectAdmission();
    const operationId = "initial-" + "c".repeat(40), syncId = "affairs-" + "c".repeat(40);
    const pump = Object.assign(vi.fn(async () => undefined), { drainForMigration: vi.fn(async () => undefined), resumeAfterMigration: vi.fn() });
    let finishWorker!: (value: object) => void;
    const heldWorker = new Promise<object>(resolve => { finishWorker = resolve; });
    let finishQueue!: () => void;
    const heldQueue = new Promise<void>(resolve => { finishQueue = resolve; });
    const releaseHostAdmission = vi.fn(), releaseRegistry = vi.fn();
    let restartJobDrained = false, crashedJobDrained = false;
    const runWorker = vi.fn(async () => kind === "revoked" ? await heldWorker : ["conflict", "slow", "busy"].includes(kind)
      ? { state: "pending", code: "affairs_conflicts", conflictCount: 2, syncId, readyForCutover: false }
      : { state: "unknown", syncId, readyForCutover: false });
    Object.assign(context, { windowProvider: provider, projectAdmission: admission, mkdirSync, readFileSync,
      LegacyReminderSourceFence: vi.fn(function () { return { drainIngress: async () => {} }; }),
      createLegacyReminderSourceResolver: () => () => null, instancesRegistryPath: () => registryPath,
      readRegistry: async () => registryData, registeredInstancesForPhysicalRoot,
      registeredAdmissionRoot: () => physical, getTrackedWorkbenchJobPid: () => 4242,
      captureTrackedWorkbenchJobNaturalRetirement: () => job, startManagedLegacyReminderRetirement,
      desktopLifecycleCoordinator: { pendingReason: () => null }, mainWorkbenchCloseStore: { currentTransaction: () => null },
      pendingWorkbenchCloseAck: null, launcherLifecycleSupervisor: { snapshot: () => null, captureExecutionDrain: async () => {} },
      AssistantProjectLifecycleRequestStore: function ({ directory }: { directory: string }) {
        const store = new AssistantProjectLifecycleRequestStore({ directory });
        return { get: (id: string) => store.get(id), reserve: (request: { requestId: string; projectId: string; operation: "start" }) =>
          store.reserve({ requestId: request.requestId, projectId: request.projectId, operation: request.operation }) };
      }, runReminderOfflineJob: runWorker, resolveProjectsHome: () => root,
      existingMainLineCommandQueueForProject: () => kind === "slow" ? { captureExecutionDrain: () => heldQueue } : undefined,
      startAssistantReminderPump: vi.fn(() => pump),
      InitialMigrationResults: vi.fn(function () { return { get: vi.fn(async () => null) }; }),
      recoverInitialMigrations: vi.fn(async () => []), verifyInitialMigrationResult: vi.fn() });
    let barrierBusy = kind === "busy";
    Object.assign(host, { prepareInitialMigration: vi.fn(async () => true), reminderHandoffReceipt: vi.fn(async () => "pending"),
      reminderHandoffSource: vi.fn(async () => ({ operationId, syncId, registryDigest: "d".repeat(64) })),
      beginMigrationAdmission: () => ({ drained: Promise.resolve(), seal: async () => {}, release: releaseHostAdmission }),
      migrationBarrier: vi.fn(async (op: string) => {
        if (kind === "barrier_crash" || kind === "retirement_crash" && op === "release") throw new Error("host unavailable");
        if (op === "status" && barrierBusy) { barrierBusy = false; return "busy"; }
        return op === "release" ? "idle" : "ready";
      }),
      prepareDeadForMigrationRetirement: vi.fn(() => ["barrier_crash", "retirement_crash"].includes(kind) && crashedJobDrained),
      snapshot: vi.fn(() => ({ state: "failed" })),
      startForMigration: vi.fn(async () => {
        if (kind === "failed_reopen" && !restartJobDrained) throw new Error("startup Job still alive");
      }),
      prepareForMigrationRestart: vi.fn(() => {
        if (kind === "failed_reopen" && host.startForMigration.mock.calls.length && !restartJobDrained)
          throw new Error("original Job not drained");
      }) });
    await context.start(paths);
    const registry = context.launcherAssistantProjects;
    registry.registration = vi.fn(() => registration);
    registry.withHistoryImport = vi.fn(async (_id: string, work: (revision: number) => Promise<unknown>) => work(0));
    registry.beginMigrationTransition = vi.fn(() => ({ drained: Promise.resolve(), release: releaseRegistry }));
    registry.retireHostForMigration = vi.fn(async () => kind !== "retirement_crash" || crashedJobDrained);
    registry.withPreHostSource = vi.fn(async (_id: string, work: (lease: unknown) => Promise<unknown>) => {
      const result = await work({ revision: 0, registration, check: () => {} });
      if (kind === "unknown" || kind === "failed_reopen") registry.hasPendingPreHostRecovery.mockReturnValue(true);
      return result;
    });
    const control = context.AssistantHost.mock.calls[0][0].mainControl;
    const request = { action: "initial_migration_queue", projectId: id, previewId: "b".repeat(64), turnId: "turn",
      category: "reminder_handoff", operationId: "initial-" + "c".repeat(40), deliveryId: "d".repeat(32), timeoutMs: 10000 };
    expect((await control(request)).state).toBe("queued");
    await vi.waitFor(() => expect(admission.hasSeals()).toBe(true));
    const receiptRequest = { action: "initial_migration_receipt", projectId: id, category: "reminder_handoff", operationId: request.operationId };
    await vi.waitFor(async () => expect(await control(receiptRequest)).toMatchObject({ state: "queued", waitingFor: "window",
      operationId: request.operationId, readyForCutover: false }));
    expect(windowClose).not.toHaveBeenCalled();
    expect(jobExited).toBe(false);
    expect(runWorker).not.toHaveBeenCalled();
    expect(host.stop).not.toHaveBeenCalled();
    closePending = true; closed = true; // The existing user close, not migration.
    await vi.waitFor(async () => expect(await control(receiptRequest)).toMatchObject({ waitingFor: "close_transaction" }));
    expect(admission.hasSeals()).toBe(true);
    closePending = false; jobExited = true;
    if (["barrier_crash", "retirement_crash"].includes(kind)) {
      await vi.waitFor(() => expect(host.prepareDeadForMigrationRetirement).toHaveBeenCalled(), { timeout: 4000 });
      expect(registry.retireHostForMigration).toHaveBeenCalledTimes(kind === "barrier_crash" ? 0 : 1);
      expect(releaseRegistry).not.toHaveBeenCalled();
      expect(releaseHostAdmission).not.toHaveBeenCalled();
      expect(pump.resumeAfterMigration).not.toHaveBeenCalled();
      expect(runWorker).not.toHaveBeenCalled();
      crashedJobDrained = true;
      await vi.waitFor(() => expect(host.startForMigration).toHaveBeenCalledOnce(), { timeout: 4000 });
      await vi.waitFor(() => expect(pump.resumeAfterMigration).toHaveBeenCalledOnce());
      expect(registry.retireHostForMigration).toHaveBeenCalledTimes(kind === "barrier_crash" ? 1 : 2);
      expect(runWorker).not.toHaveBeenCalled();
      expect(host.stop).not.toHaveBeenCalled();
      context.shutdownApproved = true;
      await context.stop();
      return;
    }
    if (kind === "slow") {
      await new Promise(resolve => setTimeout(resolve, 1250));
      expect(runWorker).not.toHaveBeenCalled();
      expect(admission.hasSeals()).toBe(true);
      finishQueue();
    }
    await vi.waitFor(() => expect(runWorker).toHaveBeenCalledOnce(), { timeout: 4000 });
    if (kind === "revoked") {
      let entered = false;
      const incoming = admission.observe(() => { throw new Error("unbound"); }, async () => { entered = true; });
      await new Promise(resolve => setTimeout(resolve, 50));
      expect(entered).toBe(false);
      finishWorker({ state: "pending", code: "affairs_conflicts", conflictCount: 2, syncId, readyForCutover: false });
      await incoming;
      expect(entered).toBe(true);
    }
    if (kind === "failed_reopen") {
      await vi.waitFor(() => expect(host.startForMigration).toHaveBeenCalledOnce());
      await new Promise(resolve => setTimeout(resolve, 1200));
      expect(host.startForMigration).toHaveBeenCalledOnce();
      expect(releaseRegistry).not.toHaveBeenCalled();
      expect(releaseHostAdmission).not.toHaveBeenCalled();
      expect(pump.resumeAfterMigration).not.toHaveBeenCalled();
      expect(admission.hasSeals()).toBe(true);
      expect(host.start).toHaveBeenCalledOnce();
      expect(host.stop).not.toHaveBeenCalled();
      restartJobDrained = true;
      await vi.waitFor(() => expect(host.startForMigration).toHaveBeenCalledTimes(2), { timeout: 4000 });
    }
    await vi.waitFor(() => expect(admission.hasSeals()).toBe(false));
    if (kind === "failed_reopen") {
      expect(releaseRegistry).toHaveBeenCalledOnce();
      expect(releaseHostAdmission).toHaveBeenCalledOnce();
      expect(pump.resumeAfterMigration).toHaveBeenCalledOnce();
    }
    if (kind === "busy") {
      expect(pump.drainForMigration).toHaveBeenCalledTimes(2);
      expect(pump.resumeAfterMigration).toHaveBeenCalledTimes(2);
    }
    if (kind === "unknown" || kind === "failed_reopen") expect(host.prepareForMigrationRestart).toHaveBeenCalledWith(projectSnapshot, true);
    expect(await control(receiptRequest)).toMatchObject(["conflict", "slow", "busy"].includes(kind)
      ? { state: "pending", code: "affairs_conflicts", conflictCount: 2, syncId, readyForCutover: false }
      : { state: "unknown", code: "unknown", readyForCutover: false });
    const restartedStore = new AssistantProjectLifecycleRequestStore({ directory: join(root, "assistant", "reminder-handoff-attempts") });
    expect((await restartedStore.get(`${syncId}.result`))?.request.projectId ?? null).toBe(["conflict", "slow", "busy"].includes(kind) ? "conflicts-2" : null);
    await control(request);
    await new Promise(resolve => setTimeout(resolve, 350));
    expect(runWorker).toHaveBeenCalledOnce();
    expect(windowClose).not.toHaveBeenCalled();
    expect(job.release).toHaveBeenCalledOnce();
    context.shutdownApproved = true;
    await context.stop();
    // A new startup gets a new store instance over the same durable attempts.
    context.launcherAssistantStarting = null;
    context.launcherAssistantStopping = null;
    context.launcherAssistantStartupAbort = new AbortController();
    context.shutdownApproved = false;
    runWorker.mockClear();
    await context.start(paths);
    const restartedControl = context.AssistantHost.mock.calls.at(-1)[0].mainControl;
    expect(await restartedControl(receiptRequest)).toMatchObject(["conflict", "slow", "busy"].includes(kind)
      ? { state: "pending", code: "affairs_conflicts", conflictCount: 2, syncId, readyForCutover: false }
      : { state: "unknown", code: "unknown", readyForCutover: false });
    await restartedControl(request);
    await new Promise(resolve => setTimeout(resolve, 350));
    expect(runWorker).not.toHaveBeenCalled();
    context.shutdownApproved = true;
    await context.stop();
  }, 10000);

  it("retries a busy migration without stopping the host, then executes and exposes the original receipt", async () => {
    const { context, host, window, paths } = fixture();
    const operationId = "initial-" + "a".repeat(40);
    let visible = false;
    window.open.mockImplementation(async (options?: { show?: boolean }) => { visible = options?.show !== false; });
    context.BrowserWindow.getAllWindows.mockImplementation(() => [{ isDestroyed: () => false, isVisible: () => visible,
      webContents: { getURL: () => "vibelution-launcher://launcher/launcher-assistant" } }]);
    context.process.env.VIBELUTION_INITIAL_MIGRATION_EXPERIMENT = "1";
    context.InitialMigrationResults = vi.fn(function () { return { get: vi.fn(async () => null) }; });
    context.verifyInitialMigrationResult = vi.fn();
    context.recoverInitialMigrations = vi.fn().mockResolvedValueOnce([])
      .mockResolvedValueOnce([{ operationId, state: "completed" }]);
    const reminders = Object.assign(vi.fn(async () => undefined), {
      drainForMigration: vi.fn(async () => undefined), resumeAfterMigration: vi.fn(),
    });
    context.startAssistantReminderPump = vi.fn(() => reminders);
    Object.assign(host, {
      prepareInitialMigration: vi.fn(async () => true),
      beginMigrationAdmission: vi.fn(() => ({ drained: Promise.resolve(), seal: vi.fn(async () => undefined), release: vi.fn() })),
      migrationBarrier: vi.fn(async (operation: string) => operation === "prepare" ? "probing"
        : operation === "release" ? "idle" : "busy"),
      prepareForMigrationRestart: vi.fn(),
    });
    await context.start(paths);
    const registry = context.launcherAssistantProjects;
    registry.withHistoryImport = vi.fn(async (_id: string, work: (revision: number) => Promise<unknown>) => work(0));
    registry.beginMigrationTransition = vi.fn(() => ({ drained: Promise.resolve(), release: vi.fn() }));
    registry.retireHostForMigration = vi.fn(async () => true);
    const control = context.AssistantHost.mock.calls[0][0].mainControl;
    const request = { action: "initial_migration_queue", projectId: "project:one", previewId: "b".repeat(64),
      turnId: "turn", category: "personal", operationId, deliveryId: "c".repeat(32), timeoutMs: 10000 };
    expect((await control(request)).state).toBe("queued");
    await vi.waitFor(() => expect(host.migrationBarrier).toHaveBeenCalledWith("release"), { timeout: 5000 });
    expect(registry.retireHostForMigration).not.toHaveBeenCalled();
    expect(host.stop).not.toHaveBeenCalled();
    host.migrationBarrier.mockImplementation(async (operation: string) => operation === "prepare" ? "probing"
      : operation === "release" ? "idle" : "ready");
    await vi.waitFor(() => expect(context.recoverInitialMigrations).toHaveBeenCalledTimes(2), { timeout: 5000 });
    await vi.waitFor(() => expect(host.prepareForMigrationRestart).toHaveBeenCalledOnce(), { timeout: 5000 });
    const receipt = await control({ action: "initial_migration_receipt", projectId: request.projectId,
      category: request.category, operationId });
    expect(receipt).toMatchObject({ operationId, state: "completed", code: "completed" });
    expect(host.stop).not.toHaveBeenCalled();
    expect(context.dialog.showMessageBox).not.toHaveBeenCalled();
    const tray = source.slice(source.indexOf("desktopTray = createDesktopTray(paths,"));
    const open = tray.match(/openAssistant:\s*(\(\)\s*=>\s*\{[\s\S]*?\n    \}),/);
    if (!open) throw new Error("Missing normal tray assistant action");
    runInNewContext(`globalThis.openNormalTray = (${open[1]});`, context);
    context.openNormalTray();
    await vi.waitFor(() => expect(context.dialog.showMessageBox).toHaveBeenCalledWith(expect.objectContaining({
      title: "个人助理迁移结果", detail: expect.stringContaining(operationId),
    })));
    await context.stop();
  }, 15000);

  it.each(["resume", "shutdown", "shutdown_first", "late_wait_exit", "late_inflight_exit"])("persists a crashed initial migration before %s without dispatching its queued operation", async mode => {
    const { context, host, paths } = fixture();
    const operationId = "initial-" + "e".repeat(40);
    const root = mkdtempSync(join(tmpdir(), "initial-crash-receipt-")); ownedRoots.push(root);
    const directory = join(root, "results"), results = new InitialMigrationResults(directory);
    let allowReceipt = false;
    const originalRecordUnknown = results.recordUnknown.bind(results);
    const writeReceipt = vi.spyOn(results, "recordUnknown").mockImplementation(async id => {
      if (!allowReceipt) throw new Error("receipt unavailable");
      return await originalRecordUnknown(id);
    });
    context.InitialMigrationResults = vi.fn(function () { return results; });
    context.recoverInitialMigrations = vi.fn(async () => []);
    context.verifyInitialMigrationResult = vi.fn();
    const reminders = Object.assign(vi.fn(async () => undefined), {
      drainForMigration: vi.fn(async () => undefined), resumeAfterMigration: vi.fn(),
    });
    let finishReminderDrain!: () => void;
    if (["late_wait_exit", "late_inflight_exit"].includes(mode)) reminders.drainForMigration.mockImplementation(async () => await new Promise<void>(resolve => { finishReminderDrain = resolve; }));
    context.startAssistantReminderPump = vi.fn(() => reminders);
    const releaseAdmission = vi.fn(), releaseRegistry = vi.fn();
    let drained = false;
    let failBarrier!: (error: Error) => void;
    Object.assign(host, {
      prepareInitialMigration: vi.fn(async () => true),
      beginMigrationAdmission: vi.fn(() => ({ drained: Promise.resolve(), seal: vi.fn(async () => undefined), release: releaseAdmission })),
      migrationBarrier: vi.fn(async () => {
        if (mode === "shutdown_first") return await new Promise((_resolve, reject) => { failBarrier = reject; });
        throw new Error("host unavailable");
      }),
      prepareDeadForMigrationRetirement: vi.fn(() => drained),
      prepareForMigrationRestart: vi.fn(), startForMigration: vi.fn(async () => undefined),
    });
    await context.start(paths);
    const registry = context.launcherAssistantProjects;
    registry.withHistoryImport = vi.fn(async (_id: string, work: (revision: number) => Promise<unknown>) => work(0));
    registry.beginMigrationTransition = vi.fn(() => ({ drained: Promise.resolve(), release: releaseRegistry }));
    registry.retireHostForMigration = vi.fn(async () => true);
    const control = context.AssistantHost.mock.calls[0][0].mainControl;
    const request = { action: "initial_migration_queue", projectId: "project:one", previewId: "b".repeat(64),
      turnId: "turn", category: "personal", operationId, deliveryId: "c".repeat(32), timeoutMs: 10000 };
    expect((await control(request)).state).toBe("queued");
    if (["late_wait_exit", "late_inflight_exit"].includes(mode)) {
      await vi.waitFor(() => expect(finishReminderDrain).toBeTypeOf("function"), { timeout: 4000 });
      const lateId = "initial-" + "f".repeat(40);
      let finishPrepare!: (value: boolean) => void;
      if (mode === "late_inflight_exit") host.prepareInitialMigration.mockImplementationOnce(async () => await new Promise<boolean>(resolve => { finishPrepare = resolve; }));
      const late = control({ ...request, operationId: lateId, deliveryId: "d".repeat(32) });
      if (mode === "late_inflight_exit") {
        await vi.waitFor(() => expect(finishPrepare).toBeTypeOf("function"));
        host.beginMigrationAdmission.mockImplementation(() => ({ drained: late.then(() => undefined), seal: () => late.then(() => undefined), release: releaseAdmission }));
        registry.beginMigrationTransition.mockImplementation(() => ({ drained: late.then(() => undefined), release: releaseRegistry }));
      } else expect((await late).state).toBe("queued");
      context.shutdownApproved = true;
      let stopped = false;
      const stopping = context.stop().then(() => { stopped = true; });
      finishReminderDrain();
      if (mode === "late_inflight_exit") {
        await new Promise(resolve => setTimeout(resolve, 100));
        expect(stopped).toBe(false);
        expect(writeReceipt).not.toHaveBeenCalled();
        finishPrepare(true);
        expect((await late).state).toBe("queued");
      }
      await vi.waitFor(() => expect(writeReceipt).toHaveBeenCalled(), { timeout: 4000 });
      expect(stopped).toBe(false);
      expect(registry.retireHostForMigration).not.toHaveBeenCalled();
      expect(releaseAdmission).not.toHaveBeenCalled();
      expect(releaseRegistry).not.toHaveBeenCalled();
      allowReceipt = true;
      await stopping;
      const reopenedResults = new InitialMigrationResults(directory);
      expect(await reopenedResults.get(operationId)).toBe("unknown");
      expect(await reopenedResults.get(lateId)).toBe("unknown");
      expect(context.recoverInitialMigrations).toHaveBeenCalledOnce();
      return;
    }
    if (mode === "shutdown_first") {
      await vi.waitFor(() => expect(failBarrier).toBeTypeOf("function"), { timeout: 4000 });
      context.shutdownApproved = true;
      let stopped = false;
      const stopping = context.stop().then(() => { stopped = true; });
      failBarrier(new Error("host unavailable"));
      await vi.waitFor(() => expect(writeReceipt).toHaveBeenCalled(), { timeout: 4000 });
      expect(stopped).toBe(false);
      expect(registry.retireHostForMigration).not.toHaveBeenCalled();
      expect(releaseAdmission).not.toHaveBeenCalled();
      expect(releaseRegistry).not.toHaveBeenCalled();
      expect(reminders.resumeAfterMigration).not.toHaveBeenCalled();
      allowReceipt = true;
      await stopping;
      expect(await new InitialMigrationResults(directory).get(operationId)).toBe("unknown");
      expect(host.startForMigration).not.toHaveBeenCalled();
      expect(context.recoverInitialMigrations).toHaveBeenCalledOnce();
      return;
    }
    await vi.waitFor(() => expect(host.prepareDeadForMigrationRetirement).toHaveBeenCalled(), { timeout: 5000 });
    expect(registry.retireHostForMigration).not.toHaveBeenCalled();
    expect(releaseAdmission).not.toHaveBeenCalled();
    expect(releaseRegistry).not.toHaveBeenCalled();
    expect(reminders.resumeAfterMigration).not.toHaveBeenCalled();
    drained = true;
    await vi.waitFor(() => expect(writeReceipt).toHaveBeenCalled(), { timeout: 4000 });
    expect(registry.retireHostForMigration).not.toHaveBeenCalled();
    expect(releaseAdmission).not.toHaveBeenCalled();
    expect(releaseRegistry).not.toHaveBeenCalled();
    expect(reminders.resumeAfterMigration).not.toHaveBeenCalled();
    if (mode === "shutdown") {
      context.shutdownApproved = true;
      let stopped = false;
      const stopping = context.stop().then(() => { stopped = true; });
      await new Promise(resolve => setTimeout(resolve, 100));
      expect(stopped).toBe(false);
      allowReceipt = true;
      await stopping;
      expect(await new InitialMigrationResults(directory).get(operationId)).toBe("unknown");
      expect(host.startForMigration).not.toHaveBeenCalled();
      expect(context.recoverInitialMigrations).toHaveBeenCalledOnce();
      return;
    }
    allowReceipt = true;
    await vi.waitFor(() => expect(host.startForMigration).toHaveBeenCalledOnce(), { timeout: 4000 });
    await vi.waitFor(() => expect(reminders.resumeAfterMigration).toHaveBeenCalledOnce());
    await new Promise(resolve => setTimeout(resolve, 1250));
    expect(context.recoverInitialMigrations).toHaveBeenCalledOnce(); // Initial startup only; no migration Job.
    expect(await new InitialMigrationResults(directory).get(operationId)).toBe("unknown");
    expect(await control({ action: "initial_migration_receipt", projectId: request.projectId,
      category: request.category, operationId })).toMatchObject({ state: "unknown", code: "unknown" });
    expect(await control(request)).toMatchObject({ state: "unknown", code: "unknown" });
    expect(host.prepareInitialMigration).toHaveBeenCalledOnce();
    expect(host.stop).not.toHaveBeenCalled();
    context.shutdownApproved = true;
    await context.stop();
  }, 15000);

  it("exits a migration with an unanswered reminder dialog after draining its in-flight click", async () => {
    const { context, host, paths } = fixture();
    const root = mkdtempSync(join(tmpdir(), "initial-reminder-exit-")); ownedRoots.push(root);
    const directory = join(root, "results"), operationId = "initial-" + "a".repeat(40);
    context.InitialMigrationResults = vi.fn(function () { return new InitialMigrationResults(directory); });
    context.recoverInitialMigrations = vi.fn(async () => []);
    context.verifyInitialMigrationResult = vi.fn();
    let click!: () => void, finishClick!: () => void;
    const pendingClick = new Promise<void>(resolve => { finishClick = resolve; });
    const event = { id: `reminder:20261027:${"a".repeat(64)}`, kind: "affair_reminder" as const, severity: "medium" as const,
      title: "Reminder", body: "Due", targetUrl: "", attemptToken: "b".repeat(64), recoveredFallback: false };
    const reminderHost = { snapshot: () => ({ state: "ready" as const, errorCode: null }),
      nextReminder: vi.fn().mockResolvedValueOnce(event).mockResolvedValue(null),
      settleReminder: vi.fn(async (_event, _channel, clicked) => { if (clicked) await pendingClick; }),
      fallbackReminder: vi.fn(async () => undefined) };
    const pump = startAssistantReminderPump({ host: reminderHost, available: () => true,
      notify: async (_notice, _recovered, onClick, _failure, fallback) => {
        click = onClick; fallback(new Promise<boolean>(() => {})); return "attention_fallback";
      }, openAssistant: vi.fn(), onError: vi.fn() });
    const drain = vi.spyOn(pump, "drainForMigration");
    const stopPump = Object.assign(vi.fn(async () => await pump()), {
      drainForMigration: () => pump.drainForMigration(), resumeAfterMigration: () => pump.resumeAfterMigration(),
    });
    context.startAssistantReminderPump = vi.fn(() => stopPump);
    const releaseAdmission = vi.fn(), releaseRegistry = vi.fn();
    Object.assign(host, { prepareInitialMigration: vi.fn(async () => true),
      beginMigrationAdmission: vi.fn(() => ({ drained: Promise.resolve(), seal: vi.fn(async () => undefined), release: releaseAdmission })) });
    await context.start(paths);
    const registry = context.launcherAssistantProjects;
    registry.withHistoryImport = vi.fn(async (_id: string, work: (revision: number) => Promise<unknown>) => work(0));
    registry.beginMigrationTransition = vi.fn(() => ({ drained: Promise.resolve(), release: releaseRegistry }));
    const control = context.AssistantHost.mock.calls[0][0].mainControl;
    await vi.waitFor(() => expect(click).toBeTypeOf("function"));
    click();
    await vi.waitFor(() => expect(reminderHost.settleReminder).toHaveBeenCalledWith(event, "attention_fallback", true));
    expect((await control({ action: "initial_migration_queue", projectId: "project:one", previewId: "b".repeat(64),
      turnId: "turn", category: "personal", operationId, deliveryId: "c".repeat(32), timeoutMs: 10000 })).state).toBe("queued");
    await vi.waitFor(() => expect(drain).toHaveBeenCalled(), { timeout: 4000 });
    context.shutdownApproved = true;
    let stopped = false;
    const stopping = context.stop().then(() => { stopped = true; });
    await vi.waitFor(() => expect(stopPump).toHaveBeenCalledOnce(), { timeout: 4000 });
    expect(await new InitialMigrationResults(directory).get(operationId)).toBe("unknown");
    await new Promise(resolve => setTimeout(resolve, 2100));
    expect(stopped).toBe(false); // The admitted click still owns its settlement.
    expect(releaseAdmission).not.toHaveBeenCalled();
    expect(releaseRegistry).not.toHaveBeenCalled();
    finishClick();
    await stopping;
    expect(stopped).toBe(true);
    expect(context.recoverInitialMigrations).toHaveBeenCalledOnce();
  }, 12000);

  it("does not retire while an already returned lifecycle command is still executing", async () => {
    const { context, host, paths, projectSnapshot } = fixture();
    projectSnapshot.projects = { "project:one": "fixture-project" };
    const operationId = "initial-" + "d".repeat(40);
    context.InitialMigrationResults = vi.fn(function () { return { get: vi.fn(async () => null) }; });
    context.recoverInitialMigrations = vi.fn().mockResolvedValueOnce([])
      .mockResolvedValueOnce([{ operationId, state: "completed" }]);
    context.verifyInitialMigrationResult = vi.fn();
    const reminders = Object.assign(vi.fn(async () => undefined), {
      drainForMigration: vi.fn(async () => undefined), resumeAfterMigration: vi.fn(),
    });
    context.startAssistantReminderPump = vi.fn(() => reminders);
    let finish!: () => void;
    const execution = new Promise<void>(done => { finish = done; });
    context.existingMainLineCommandQueueForProject = vi.fn(() => ({ captureExecutionDrain: () => execution }));
    Object.assign(host, { prepareInitialMigration: vi.fn(async () => true),
      beginMigrationAdmission: vi.fn(() => ({ drained: Promise.resolve(), seal: vi.fn(async () => undefined), release: vi.fn() })),
      migrationBarrier: vi.fn(async (op: string) => op === "prepare" ? "probing" : op === "release" ? "idle" : "ready"),
      prepareForMigrationRestart: vi.fn() });
    await context.start(paths);
    const registry = context.launcherAssistantProjects;
    registry.snapshot = vi.fn(() => projectSnapshot);
    registry.withHistoryImport = vi.fn(async (_id: string, work: (revision: number) => Promise<unknown>) => work(0));
    registry.beginMigrationTransition = vi.fn(() => ({ drained: Promise.resolve(), release: vi.fn() }));
    registry.retireHostForMigration = vi.fn(async () => true);
    const control = context.AssistantHost.mock.calls[0][0].mainControl;
    await control({ action: "initial_migration_queue", projectId: "project:one", previewId: "b".repeat(64),
      turnId: "turn", category: "personal", operationId, deliveryId: "c".repeat(32), timeoutMs: 10000 });
    await vi.waitFor(() => expect(context.existingMainLineCommandQueueForProject).toHaveBeenCalled(), { timeout: 5000 });
    expect(registry.retireHostForMigration).not.toHaveBeenCalled();
    expect(host.stop).not.toHaveBeenCalled();
    finish();
    await vi.waitFor(() => expect(registry.retireHostForMigration).toHaveBeenCalledOnce(), { timeout: 5000 });
    await vi.waitFor(() => expect(host.prepareForMigrationRestart).toHaveBeenCalledOnce(), { timeout: 5000 });
    await context.stop();
  }, 15000);

  it("starts the host with an unknown receipt when the intent listing cannot be read", async () => {
    const { context, host, paths } = fixture();
    context.process.env.VIBELUTION_INITIAL_MIGRATION_EXPERIMENT = "1";
    context.InitialMigrationResults = vi.fn(function () { return { get: vi.fn(async () => null) }; });
    context.recoverInitialMigrations = vi.fn(async () => { throw new Error("INTENTS_UNAVAILABLE"); });
    context.verifyInitialMigrationResult = vi.fn();
    await context.start(paths);
    expect(host.start).toHaveBeenCalledOnce();
    context.launcherAssistantProjects.withHistoryImport = vi.fn(async (_id: string, work: () => Promise<unknown>) => work());
    const control = context.AssistantHost.mock.calls[0][0].mainControl;
    const receipt = await control({ action: "initial_migration_receipt", projectId: "project:one",
      category: "personal", operationId: "initial-" + "a".repeat(40) });
    expect(receipt.state).toBe("unknown");
  });

  it("leaves damaged result storage untouched and starts with unknown receipts", async () => {
    const { context, host, paths } = fixture();
    const root = mkdtempSync(join(tmpdir(), "assistant-start-damaged-")); ownedRoots.push(root);
    paths.userDataRoot = root;
    const directory = join(root, "assistant", "initial-migration-results"); mkdirSync(directory, { recursive: true });
    const operationId = "initial-" + "a".repeat(40);
    const damaged = join(directory, createHash("sha256").update(operationId).digest("hex") + ".json");
    writeFileSync(damaged, "{broken");
    context.process.env.VIBELUTION_INITIAL_MIGRATION_EXPERIMENT = "1";
    context.InitialMigrationResults = InitialMigrationResults;
    context.recoverInitialMigrations = vi.fn();
    await context.start(paths);
    expect(host.start).toHaveBeenCalledOnce();
    expect(context.recoverInitialMigrations).not.toHaveBeenCalled();
    context.launcherAssistantProjects.withHistoryImport = vi.fn(async (_id: string, work: () => Promise<unknown>) => work());
    const control = context.AssistantHost.mock.calls[0][0].mainControl;
    const receipt = await control({ action: "initial_migration_receipt", projectId: "project:one",
      category: "personal", operationId });
    expect(receipt.state).toBe("unknown");
    expect(readFileSync(damaged, "utf8")).toBe("{broken");
  });

  it("retries owned cleanup after an earlier exit attempt fails", async () => {
    const { context, paths } = fixture();
    await context.start(paths);
    const stop = context.launcherAssistantProjects.stop;
    stop.mockRejectedValueOnce(new Error("still running"));
    await expect(context.stop()).rejects.toThrow("still running");
    expect(context.launcherAssistantExitReady).toBe(false);
    await expect(context.stop()).resolves.toBeUndefined();
    expect(stop).toHaveBeenCalledTimes(2);
    expect(context.launcherAssistantExitReady).toBe(true);
  });

  it("keeps quit pending until recovery has released its owned writer", async () => {
    const { context, host, paths } = fixture();
    context.process.env.VIBELUTION_INITIAL_MIGRATION_EXPERIMENT = "1";
    context.InitialMigrationResults = vi.fn(function () { return {}; });
    context.verifyInitialMigrationResult = vi.fn();
    let finish!: (value: unknown[]) => void;
    context.recoverInitialMigrations = vi.fn(() => new Promise(resolve => { finish = resolve; }));
    const starting = context.start(paths);
    await vi.waitFor(() => expect(context.recoverInitialMigrations).toHaveBeenCalledOnce());
    context.shutdownApproved = true;
    let stopped = false;
    const stopping = context.stop().then(() => { stopped = true; });
    expect(context.launcherAssistantStartupAbort.signal.aborted).toBe(true);
    await Promise.resolve();
    expect(stopped).toBe(false);
    expect(host.start).not.toHaveBeenCalled();
    finish([]);
    await Promise.all([starting, stopping]);
    expect(stopped).toBe(true);
    expect(host.start).not.toHaveBeenCalled();
  });

  it("intercepts app quit before a host exists and waits for recovery to retire", async () => {
    const { context, host, paths } = fixture();
    context.process.env.VIBELUTION_INITIAL_MIGRATION_EXPERIMENT = "1";
    context.InitialMigrationResults = vi.fn(function () { return {}; });
    context.verifyInitialMigrationResult = vi.fn();
    let finish!: (value: unknown[]) => void;
    context.recoverInitialMigrations = vi.fn(() => new Promise(resolve => { finish = resolve; }));
    const beforeQuit = ast.statements.find(node => isExpressionStatement(node) && isCallExpression(node.expression)
      && node.expression.expression.getText(ast) === "app.on" && node.expression.arguments[0]?.getText(ast) === '"before-quit"')!;
    runInNewContext(transpileModule(beforeQuit.getFullText(ast), { compilerOptions: { target: ScriptTarget.ES2022 } }).outputText, context);
    const starting = context.start(paths);
    await vi.waitFor(() => expect(context.recoverInitialMigrations).toHaveBeenCalledOnce());
    const handler = context.app.on.mock.calls.find(([name]: [string]) => name === "before-quit")[1];
    const event = { preventDefault: vi.fn() };
    handler(event);
    expect(event.preventDefault).toHaveBeenCalledOnce();
    expect(context.launcherAssistantStartupAbort.signal.aborted).toBe(true);
    expect(context.app.quit).not.toHaveBeenCalled();
    finish([]);
    await starting;
    await vi.waitFor(() => expect(context.app.quit).toHaveBeenCalledOnce());
    expect(host.start).not.toHaveBeenCalled();
  });

  it("bootstraps persisted projects without granting the workspace or starting its Python", async () => {
    const { context, projectSnapshot, paths } = fixture();
    Object.assign(projectSnapshot, { revision: 8, projects: { "persisted:uuid": "known-root" } });
    await context.start(paths);
    expect(context.AssistantHost.mock.calls[0][0].projectSnapshot).toEqual(projectSnapshot);
    expect(context.readProjectId).not.toHaveBeenCalled();
    expect(context.AssistantHost.mock.calls[0][0].pythonPath).toBe("sealed-pythonw");
  });

  it("rejects a corrupt persisted registry before resource resolution or host creation", async () => {
    const { context, paths } = fixture();
    context.AssistantProjectRegistryConnection.mockImplementation(() => { throw new Error("PROJECT_REGISTRY_INVALID"); });
    await expect(context.start(paths)).rejects.toThrow("PROJECT_REGISTRY_INVALID");
    expect(context.resolveAssistantResources).not.toHaveBeenCalled();
    expect(context.AssistantHost).not.toHaveBeenCalled();
  });

  it("opens the character during pending native readiness while shutdown waits for the host queue", async () => {
    const { context, host, window, paths } = fixture();
    let ready!: () => void;
    host.start.mockImplementation(() => new Promise<void>(done => { ready = done; }));
    await context.start(paths);
    expect(window.open).toHaveBeenCalledWith({ show: false });
    expect(host.start).toHaveBeenCalledTimes(1);
    let stopped = false;
    const stopping = context.stop().then(() => { stopped = true; });
    await Promise.resolve();
    expect(stopped).toBe(false);
    expect(host.stop).not.toHaveBeenCalled();
    ready(); await stopping;
    expect(host.stop).toHaveBeenCalledTimes(1);
    expect(context.launcherAssistantExitReady).toBe(true);
  });

  it("keeps the character available to show a native host startup failure", async () => {
    const { context, host, window, paths } = fixture();
    context.console = { ...console, warn: vi.fn() };
    host.start.mockRejectedValue(new Error("ASSISTANT_IDENTITY_INVALID"));
    await context.start(paths);
    expect(window.open).toHaveBeenCalledTimes(1);
    await vi.waitFor(() => expect(context.console.warn).toHaveBeenCalledWith("ASSISTANT_START_FAILED"));
  });

  it("never starts a process after quit wins a pending resource verification", async () => {
    const { context, paths } = fixture();
    let release!: (value: unknown) => void;
    context.resolveAssistantResources.mockImplementation(() => new Promise(resolve => { release = resolve; }));
    const start = context.start(paths);
    context.shutdownApproved = true;
    const stop = context.stop();
    release({});
    await Promise.all([start, stop]);
    expect(context.AssistantHost).not.toHaveBeenCalled();
    expect(context.launcherAssistantExitReady).toBe(true);
  });

  it("fails closed on invalid packaged resources before creating a host or tray", async () => {
    const { context, paths } = fixture();
    context.resolveAssistantResources.mockRejectedValue(new Error("ASSISTANT_PAYLOAD_INTEGRITY_FAILED"));
    await expect(context.start(paths)).rejects.toThrow("ASSISTANT_PAYLOAD_INTEGRITY_FAILED");
    expect(context.AssistantHost).not.toHaveBeenCalled();
    expect(context.createAssistantTray).not.toHaveBeenCalled();
  });
});

describe("native Launcher inventory wiring", () => {
  function refreshFixture() {
    const inventory = { schemaVersion: 1, integrationRoot: "native-root", items: [] };
    // Exact native state_refresh.py/_capture source DTO, before the store's
    // projection unwraps it. The permission observer runs before projection.
    const state: { status: unknown; branchInstances: unknown } = {
      status: { ok: true, value: { state: "ready" } }, branchInstances: { ok: true, value: inventory },
    };
    const context = {
      currentLauncherWindowTruth: () => ({ instances: [], workbench: null }),
      orchestrateLauncherApi: vi.fn(async () => state), scheduleRegistryReconciliation: vi.fn(),
      launcherAssistantProjects: { reconcile: vi.fn(async (_payload: unknown) => undefined) },
      unwrapSource,
      console: { warn: vi.fn() }, refresh: undefined as any,
    };
    runInNewContext(transpileModule(`globalThis.refresh = ${stateRefresh};`, { compilerOptions: { target: ScriptTarget.ES2022 } }).outputText, context);
    return { context, inventory, state };
  }

  it("returns successful raw native inventory while assistant apply is pending and bounds its eventual rejection", async () => {
    const { context, inventory, state } = refreshFixture();
    let failApply!: (error: Error) => void;
    context.launcherAssistantProjects.reconcile.mockImplementation(() => new Promise((_done, reject) => { failApply = reject; }));
    let complete = false;
    const refresh = context.refresh().then((result: unknown) => { complete = true; return result; });
    await vi.waitFor(() => expect(context.launcherAssistantProjects.reconcile).toHaveBeenCalledWith(inventory));
    expect(context.orchestrateLauncherApi).toHaveBeenCalledWith("state-refresh", expect.objectContaining({ path: "state-refresh" }));
    await vi.waitFor(() => expect(complete).toBe(true));
    expect(await refresh).toMatchObject(state);
    expect(context.console.warn).not.toHaveBeenCalled();
    failApply(new Error("ASSISTANT_REGISTRY_UNCONFIRMED: private diagnostic"));
    await vi.waitFor(() => expect(context.console.warn).toHaveBeenCalledTimes(1));
    expect(context.console.warn).toHaveBeenCalledWith("ASSISTANT_REGISTRY_UPDATE_FAILED");
  });

  it("never changes permissions when native observation fails", async () => {
    const { context } = refreshFixture();
    context.orchestrateLauncherApi.mockRejectedValue(new Error("native observation unavailable"));
    await expect(context.refresh()).rejects.toThrow("native observation unavailable");
    expect(context.launcherAssistantProjects.reconcile).not.toHaveBeenCalled();
  });

  it.each([
    { ok: false, errorType: "GitError", message: "inventory unavailable" },
    { ok: "true", value: { schemaVersion: 1, integrationRoot: "native-root", items: [] } },
    {}, null,
    { schemaVersion: 1, integrationRoot: "native-root", items: [] },
  ])("never applies a failed or unknown native source envelope: %s", async branchSource => {
    const { context, state } = refreshFixture();
    state.branchInstances = branchSource;
    expect((await context.refresh()).branchInstances).toEqual(branchSource);
    expect(context.launcherAssistantProjects.reconcile).not.toHaveBeenCalled();
  });

  it("preserves persisted grants on failed/malformed sources and forwards an authoritative wrapped empty inventory", async () => {
    const { context, state } = refreshFixture();
    const root = mkdtempSync(join(tmpdir(), "assistant-native-source-")); ownedRoots.push(root);
    const project = join(root, "project"); mkdirSync(project);
    const filePath = join(root, "assistant", "projects.json");
    const connection = new AssistantProjectRegistryConnection(filePath);
    context.launcherAssistantProjects.reconcile.mockImplementation(value => connection.reconcile(value));
    const inventory = { schemaVersion: 1, integrationRoot: root, items: [{ id: "worktree:task", path: project, checkedOut: true }] };
    state.branchInstances = { ok: true, value: inventory };
    await context.refresh();
    await vi.waitFor(() => expect(existsSync(filePath)).toBe(true));
    const authorized = readFileSync(filePath, "utf8");
    expect(JSON.parse(authorized).registrations[0].active).toBe(true);
    state.branchInstances = { ok: false, errorType: "GitError", message: "inventory unavailable" };
    await context.refresh();
    expect(context.launcherAssistantProjects.reconcile).toHaveBeenCalledTimes(1);
    expect(readFileSync(filePath, "utf8")).toBe(authorized);
    state.branchInstances = { ok: true, value: { ...inventory, items: [inventory.items[0], null] } };
    await context.refresh();
    await vi.waitFor(() => expect(context.console.warn).toHaveBeenCalledWith("ASSISTANT_REGISTRY_UPDATE_FAILED"));
    expect(readFileSync(filePath, "utf8")).toBe(authorized);
    const empty = { ...inventory, items: [] };
    state.branchInstances = { ok: true, value: empty };
    await context.refresh();
    await vi.waitFor(() => expect(JSON.parse(readFileSync(filePath, "utf8")).registrations[0].active).toBe(false));
    expect(context.launcherAssistantProjects.reconcile).toHaveBeenLastCalledWith(empty);
  });

  it("keeps Launcher status available after the assistant rejects or cannot confirm an update", async () => {
    const { context, state } = refreshFixture();
    context.launcherAssistantProjects.reconcile.mockRejectedValue(new Error("ASSISTANT_REGISTRY_UNCONFIRMED"));
    const refreshed = await context.refresh();
    expect(refreshed.status).toEqual(state.status);
    expect(refreshed.branchInstances).toEqual(state.branchInstances);
    expect(context.console.warn).toHaveBeenCalledWith("ASSISTANT_REGISTRY_UPDATE_FAILED");
  });
});
