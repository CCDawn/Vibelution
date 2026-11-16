import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { join } from "node:path";
import { runInNewContext } from "node:vm";
import { createSourceFile, isFunctionDeclaration, ScriptTarget, transpileModule } from "typescript";
import { describe, expect, it, vi } from "vitest";
import { PrehostRecoveryDrainedUnknown } from "../src/assistant/prehostRecoveryJob.js";
import { createBranchLifecycleCommandOwner } from "../src/lifecycle/branchLifecycleCommands.js";
import { ConfigurationReferenceLeaseBroker } from "../src/assistant/configurationReferenceLease.js";
import { isConfigurationReferenceRequest } from "../src/assistant/configurationReferenceProtocol.js";
import { createReminderTransportWarningGate, REMINDER_TRANSPORT_FAILURE_LIMIT } from "../src/assistant/reminderPump.js";

/** The resident-stack harness from assistantStartup.test.ts, narrowed to the
 * stop/cancelled-exit functions under test here. */
const source = readFileSync(new URL("../src/main.ts", import.meta.url), "utf8");
const ast = createSourceFile("main.ts", source, ScriptTarget.Latest, true);
const declarations = ["startLauncherAssistant", "stopLauncherAssistant", "resumeLauncherAssistantAfterCancelledExit"].map(name => {
  const fn = ast.statements.find(node => isFunctionDeclaration(node) && node.name?.text === name);
  if (!fn) throw new Error(`Missing ${name}`);
  return fn.getFullText(ast);
}).join("\n");

function fixture() {
  const host: Record<string, any> = { start: vi.fn(async () => undefined), stop: vi.fn(async () => undefined) };
  const window = { open: vi.fn(async () => undefined), destroyFloat: vi.fn() };
  const projectSnapshot = { schemaVersion: 1, revision: 0, projects: {} };
  let pendingStart: Promise<unknown> = Promise.resolve();
  /** The connection's own retirement misses its host unless a test opts in. */
  let connectionRetiresHost = false;
  const projects: Record<string, any> = {
    snapshot: vi.fn(() => projectSnapshot),
    hasPendingPreHostRecovery: vi.fn(() => false),
    pendingPreHostRecovery: vi.fn(() => null as { projectId: string; operationId: string } | null),
    recoverPreHostSource: vi.fn(async () => false),
    revokePreHostRecovery: vi.fn(),
    start: vi.fn(async (createHost: (snapshot: unknown, suspended: boolean) => typeof host) => {
      const result = createHost(projectSnapshot, false);
      pendingStart = result.start();
      await pendingStart; return result;
    }),
    stop: vi.fn(async () => {
      await pendingStart.catch(() => undefined);
      if (connectionRetiresHost) await host.stop();
    }),
  };
  const context: Record<string, any> = {
    launcherAssistantStarting: null, launcherAssistantStopping: null, initialMigrationReceiptFence: null, launcherAssistantStartupAbort: new AbortController(),
    launcherAssistantResume: null, launcherAssistantPaths: null,
    launcherAssistantHost: null, launcherAssistantWindow: null, launcherAssistantBrowser: null, showAssistantStartupWait: null, dismissAssistantStartupWait: null, flushAssistantMigrationFeedback: null, assistantMigrationPending: false,
    launcherAssistantProjects: null, stopLauncherAssistantReminders: null, pendingAssistantOpen: null,
    projectAdmissionExperiment: false,
    projectAdmission: null, legacyReminderAdmission: null,
    launcherAssistantExitReady: false, desktopTray: null, assistantOnly: true, shutdownApproved: false,
    app: { isPackaged: true, quit: vi.fn(), on: vi.fn(), getPath: vi.fn(() => "private") }, join, console,
    AbortController, createHash, setTimeout, clearTimeout, dialog: { showMessageBox: vi.fn(async () => ({ response: 0 })) },
    BrowserWindow: { getAllWindows: vi.fn(() => []) },
    desktopCliArgs: { hiddenPresentation: true }, desktopPythonPath: vi.fn(() => ""),
    desktopEnvironment: () => ({ VIBELUTION_CONFIG_PATH: "private-config" }),
    desktopLaunchSettings: () => ({ configPath: "private-config" }),
    process: { env: {}, resourcesPath: "resources" },
    createBranchLifecycleCommandOwner, ConfigurationReferenceLeaseBroker, isConfigurationReferenceRequest,
    createAssistantAppearanceMainControl: vi.fn(() => async () => ({ code: "unavailable" })),
    createAssistantProjectMainControl: vi.fn(() => async () => ({ state: "unknown" })),
    existingMainLineCommandQueueForProject: vi.fn(() => undefined),
    withProjectAdmission: async (_root: () => string, work: () => Promise<unknown>) => work(),
    resolveAssistantResources: vi.fn(async () => ({ sourceRoot: "sealed-source", pythonPath: "sealed-pythonw",
      pythonArguments: ["-I"], env: { VIBELUTION_CONFIG_PATH: "private-config" } })),
    readProjectId: vi.fn(() => "p"), instanceIdForProject: vi.fn(() => "i"),
    AssistantHost: vi.fn(function () { return host; }), AssistantWindow: vi.fn(function () { return window; }),
    AssistantProjectLifecycleRequestStore: vi.fn(function () { return { get: vi.fn(async () => null) }; }),
    startAssistantReminderPump: vi.fn(() => vi.fn(async () => undefined)),
    createReminderTransportWarningGate, REMINDER_TRANSPORT_FAILURE_LIMIT,
    startAssistantEventPump: vi.fn(() => ({ done: Promise.resolve() })),
    AssistantProjectRegistryConnection: vi.fn(function () { return projects; }),
    createAssistantTray: vi.fn(() => ({ destroy: vi.fn() })), requestDesktopShellExit: vi.fn(),
    requestOpenLauncherFromAssistant: vi.fn(async () => ({ opened: true })),
    PrehostRecoveryDrainedUnknown: class extends Error {},
    InitialMigrationResults: vi.fn(function () { return { get: vi.fn(async () => null) }; }),
    recoverInitialMigrations: vi.fn(async () => []),
    verifyInitialMigrationResult: vi.fn(),
    resolveSingleInstanceProvenance: vi.fn(), resolveSingleInstanceCliIntent: vi.fn(), resolveSecondInstanceIntent: vi.fn(),
    findVibelutionDeepLinkArg: vi.fn(() => null), handlePublicDeepLinkUrl: vi.fn(),
    applyPendingProjectSlot: vi.fn(), handleSecondInstanceLifecycleCommand: vi.fn(),
    requestOpenWorkbenchFromSecondInstance: vi.fn(), focusExistingDesktopShell: vi.fn(),
  };
  runInNewContext(transpileModule(`${declarations}\nglobalThis.start=startLauncherAssistant;globalThis.stop=stopLauncherAssistant;globalThis.resume=resumeLauncherAssistantAfterCancelledExit;`, {
    compilerOptions: { target: ScriptTarget.ES2022 },
  }).outputText, context);
  const paths = { resourcesRoot: "resources", workspaceRoot: "", userDataRoot: "private", desktopBundleRoot: "bundle" };
  return { context, host, window, projects, paths, setConnectionRetiresHost: (value: boolean) => { connectionRetiresHost = value; } };
}

describe("resident assistant stop orphan guard", () => {
  it("stops the resident host directly when the registry stop missed it", async () => {
    const { context, host, projects, paths, setConnectionRetiresHost } = fixture();
    setConnectionRetiresHost(false);
    // The host reports ready until its own stop ran: exactly the live shell +
    // dead-owner hybrid a cancelled exit used to leave behind.
    host.snapshot = vi.fn(() => ({ state: host.stop.mock.calls.length ? "stopped" : "ready", errorCode: null }));
    await context.start(paths);
    expect(projects.stop).not.toHaveBeenCalled();
    await context.stop();
    // The registry stop settled without touching the host; the fallback must
    // still land the resident owner in "stopped".
    expect(projects.stop).toHaveBeenCalledOnce();
    expect(host.stop).toHaveBeenCalledOnce();
    expect(context.launcherAssistantExitReady).toBe(true);
    expect(context.launcherAssistantStartupAbort.signal.aborted).toBe(true);
  });

  it("skips the direct fallback when the registry stop already retired the host", async () => {
    const { context, host, paths, setConnectionRetiresHost } = fixture();
    setConnectionRetiresHost(true);
    host.snapshot = vi.fn(() => ({ state: host.stop.mock.calls.length ? "stopped" : "ready", errorCode: null }));
    await context.start(paths);
    await context.stop();
    // The ordinary connection-owned retirement ran; no duplicate host stop.
    expect(host.stop).toHaveBeenCalledOnce();
    expect(context.launcherAssistantExitReady).toBe(true);
  });

  it("retries the retained stop once from cancelled-exit recovery when the host is failed", async () => {
    const { context, host, projects, paths, setConnectionRetiresHost } = fixture();
    setConnectionRetiresHost(false);
    host.snapshot = vi.fn(() => ({ state: host.stop.mock.calls.length >= 2 ? "stopped" : "failed", errorCode: null }));
    host.resumeAfterCancelledExit = vi.fn();
    await context.start(paths);
    // The first stop fails honestly: the host is left "failed" and the
    // surviving shell would previously skip recovery forever (every later
    // start refused by the sealed admission).
    await expect(context.stop()).rejects.toThrow("ASSISTANT_HOST_STOP_INCOMPLETE");
    expect(host.snapshot()).toMatchObject({ state: "failed" });
    await context.resume();
    expect(host.resumeAfterCancelledExit).toHaveBeenCalledOnce();
    expect(projects.start).toHaveBeenCalledTimes(2);
    expect(host.start).toHaveBeenCalledTimes(2);
    expect(context.launcherAssistantStartupAbort.signal.aborted).toBe(false);
    await context.stop();
  });

  it("keeps skipping recovery when the host still cannot reach stopped", async () => {
    const { context, host, paths, setConnectionRetiresHost } = fixture();
    setConnectionRetiresHost(false);
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    try {
      host.snapshot = vi.fn(() => ({ state: "failed", errorCode: null }));
      host.resumeAfterCancelledExit = vi.fn();
      await context.start(paths);
      await expect(context.stop()).rejects.toThrow("ASSISTANT_HOST_STOP_INCOMPLETE");
      await context.resume();
      expect(host.resumeAfterCancelledExit).not.toHaveBeenCalled();
      expect(warn.mock.calls.some(([message]) => String(message).includes("ASSISTANT_CANCELLED_EXIT_RECOVERY skipped"))).toBe(true);
    } finally {
      warn.mockRestore();
    }
  });
});
