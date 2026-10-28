import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { runInNewContext } from "node:vm";
import { createSourceFile, isCallExpression, isExpressionStatement, isFunctionDeclaration, isNewExpression, isVariableStatement, ScriptTarget, transpileModule } from "typescript";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AssistantProjectRegistryConnection } from "../src/assistant/projectRegistryConnection.js";
import { InitialMigrationResults } from "../src/assistant/initialMigrationResults.js";
import { unwrapSource } from "../src/state/launcherStateStore.js";
import { createSingleInstanceEnvelope, resolveSecondInstanceIntent, resolveSingleInstanceCliIntent, resolveSingleInstanceProvenance } from "../src/appLock.js";
import { parseDesktopCliArgs } from "../src/cli/desktopCli.js";
import { applyDesktopLaunchSettingsToEnvironment, resolveDesktopLaunchSettings } from "../src/launch/desktopLaunchSettings.js";
import { planProjectSlot, projectSlotWindowAction } from "../src/protocol/applyProjectSlot.js";
import { parseBranchInstanceRecords } from "../src/protocol/launcherControlClient.js";

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
    start: vi.fn(async (createHost: (snapshot: unknown) => typeof host) => { const result = createHost(projectSnapshot); pendingStart = result.start(); await pendingStart; return result; }),
    stop: vi.fn(async () => { await pendingStart.catch(() => undefined); await host.stop(); }),
  };
  const context: Record<string, any> = {
    launcherAssistantStarting: null, launcherAssistantStopping: null, launcherAssistantStartupAbort: new AbortController(),
    launcherAssistantHost: null, launcherAssistantWindow: null, showAssistantStartupWait: null, dismissAssistantStartupWait: null, assistantMigrationPending: false,
    launcherAssistantProjects: null, stopLauncherAssistantReminders: null, pendingAssistantOpen: null,
    launcherAssistantExitReady: false, desktopTray: null, assistantOnly: true, shutdownApproved: false,
    app: { isPackaged: true, quit: vi.fn(), on: vi.fn(), getPath: vi.fn(() => "private") }, join, console,
    AbortController, setTimeout, clearTimeout, dialog: { showMessageBox: vi.fn(async () => ({ response: 0 })) },
    desktopCliArgs: { hiddenPresentation: true }, desktopPythonPath: vi.fn(() => ""),
    desktopEnvironment: () => ({ VIBELUTION_CONFIG_PATH: "private-config" }),
    desktopLaunchSettings: () => ({ configPath: "private-config" }),
    process: { env: {}, resourcesPath: "resources" },
    createAssistantProjectMainControl: vi.fn(() => async () => ({ state: "unknown" })),
    createAssistantAppearanceMainControl: vi.fn(() => async () => ({ code: "unavailable" })),
    resolveAssistantResources: vi.fn(async () => ({ sourceRoot: "sealed-source", pythonPath: "sealed-pythonw",
      pythonArguments: ["-I"], env: { VIBELUTION_CONFIG_PATH: "private-config" } })),
    readProjectId: vi.fn(() => "p"), instanceIdForProject: vi.fn(() => "i"),
    AssistantHost: vi.fn(function () { return host; }), AssistantWindow: vi.fn(function () { return window; }),
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
  return { context, host, window, projectSnapshot, paths: { resourcesRoot: "resources", workspaceRoot: "", userDataRoot: "private", desktopBundleRoot: "bundle" } };
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
  const functions = ["ensureProjectControlPlane", "applyPendingProjectSlot"].map(name =>
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
