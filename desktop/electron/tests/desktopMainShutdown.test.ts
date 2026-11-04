import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import ts from "typescript";
import { afterEach, describe, expect, it, vi } from "vitest";
import { combineAssistantActiveWork } from "../src/assistant/lifecycleGuard.js";
import { DesktopLifecycleCoordinator } from "../src/lifecycle/desktopLifecycleCoordinator.js";
import { createDesktopShellExitDeadline, executeApprovedDesktopShellShutdown, withDesktopShellExitTimeout } from "../src/shutdown/desktopShellExit.js";
import { decideShutdown, executeShutdownAuthorizationBoundary, resolveQuitActiveWorkStatus, type ActiveWorkStatus, type ShutdownDecision } from "../src/shutdown/shutdownCoordinator.js";

const source = readFileSync(new URL("../src/main.ts", import.meta.url), "utf8");
const parsed = ts.createSourceFile("main.ts", source, ts.ScriptTarget.ES2022, true);
const names = ["confirmDesktopShellExit", "requestDesktopShellExit", "residentAssistantStatus",
  "residentAssistantActiveWork", "acquireResidentAssistantShutdownGuard", "runTrayStopAll"];
const declarations = names.map(name => {
  const declaration = parsed.statements.find(statement => ts.isFunctionDeclaration(statement) && statement.name?.text === name);
  if (!declaration) throw new Error(`Missing main function ${name}`);
  return declaration.getText(parsed);
}).join("\n");

function harness() {
  const workspace: ActiveWorkStatus = { state: "idle", message: "" };
  let hostState = "ready";
  const release = vi.fn(async () => undefined);
  const commit = vi.fn();
  const acquire = vi.fn(async () => {
    if (hostState === "stopped") throw new Error("ASSISTANT_LIFECYCLE_UNAVAILABLE");
    return { release, commit };
  });
  const stopMain = vi.fn(async (_interrupt: boolean, _signal?: AbortSignal) => undefined);
  const stopIsolated = vi.fn(async () => undefined);
  const closeSession = vi.fn(async () => undefined);
  const closeWindow = vi.fn(async (_options: { deadlineAt: number }) => ({ open: false }));
  const dialog = vi.fn(async () => ({ response: 0 }));
  const quit = vi.fn();
  const context = {
    AbortSignal, Date, Promise, setTimeout, clearTimeout,
    console: { warn: vi.fn() },
    DESKTOP_QUIT_TOTAL_BUDGET_MS: 30_000,
    QUIT_ACTIVE_WORK_STATUS_TIMEOUT_MS: 8_000,
    ASSISTANT_START_SETTLE_WAIT_MS: 5_000,
    launcherBootstrap: { mode: "attached" },
    launcherAssistantStarting: null,
    launcherAssistantHost: {
      snapshot: () => ({ state: hostState }),
      lifecycleStatus: async () => "idle",
    },
    launcherAssistantExitReady: false,
    acquireResidentAssistantLifecycleLease: acquire,
    desktopLifecycleCoordinator: new DesktopLifecycleCoordinator(),
    createDesktopShellExitDeadline, withDesktopShellExitTimeout,
    executeShutdownAuthorizationBoundary, decideShutdown, resolveQuitActiveWorkStatus,
    combineAssistantActiveWork, executeApprovedDesktopShellShutdown,
    resolveDesktopActionLoopContext: async () => ({}),
    fetchLauncherActiveWorkStatus: async () => workspace,
    localQuitActiveWorkStatus: () => workspace,
    recordDesktopExitEvent: vi.fn(),
    assistantBrowserWindow: () => null,
    dialog: { showMessageBox: dialog },
    notifyDesktopTray: vi.fn(),
    pendingWorkbenchCloseAck: null,
    joinWorkbenchCloseBackendStop: async () => false,
    stopIsolatedInstancesForApprovedShutdown: stopIsolated,
    stopMainRuntimeForApprovedShutdown: stopMain,
    closeDesktopSessionIfRegistered: closeSession,
    windowProvider: { approveWorkbenchCloseOnce: closeWindow },
    stopOwnedPythonLauncherService: async () => ({ schemaVersion: 1, status: "skipped", reason: "no_owner",
      expectedBackendPid: 0, launcherBackendPid: 0, terminatedPids: [] }),
    recordSupervisorEventFallbackLocally: vi.fn(),
    stopDesktopActionLoop: vi.fn(),
    shutdownApproved: false,
    app: { quit },
    trayQuitAllInFlight: false, trayRestartAllInFlight: false,
    trayRestartLauncherInFlight: false, shellRefreshInFlight: false,
    stopLauncherAssistant: vi.fn(async () => {
      hostState = "stopped";
      context.launcherAssistantExitReady = true;
    }),
  };
  runInNewContext(ts.transpileModule(declarations, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText, context);
  const actions = context as typeof context & {
    requestDesktopShellExit: (reason: string, confirm: boolean) => Promise<ShutdownDecision>;
    runTrayStopAll: () => Promise<void>;
  };
  return { context, workspace, release, acquire, stopMain, stopIsolated, closeSession, closeWindow, dialog, quit,
    exit: (operatorRequested = true) => actions.requestDesktopShellExit("desktop_shell_quit", operatorRequested),
    tray: () => actions.runTrayStopAll() };
}

afterEach(() => vi.useRealTimers());

function reminderNotificationHarness() {
  let initializer: ts.Expression | undefined;
  const visit = (node: ts.Node): void => {
    if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === "startAssistantReminderPump") {
      const options = node.arguments[0];
      if (options && ts.isObjectLiteralExpression(options)) {
        const property = options.properties.find(item => ts.isPropertyAssignment(item) && item.name.getText(parsed) === "notify");
        if (property && ts.isPropertyAssignment(property)) initializer = property.initializer;
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(parsed);
  if (!initializer) throw new Error("Missing native reminder notify implementation");
  const notifications: NativeNotification[] = [];
  class NativeNotification {
    static isSupported() { return true; }
    handlers = new Map<string, () => void>();
    show = vi.fn();
    close = vi.fn(() => this.handlers.get("failed")?.());
    constructor() { notifications.push(this); }
    on(event: string, listener: () => void) { this.handlers.set(event, listener); return this; }
  }
  const fallback = vi.fn(async () => ({ response: 0 }));
  const context = { setTimeout, clearTimeout, Error, console: { warn: vi.fn() }, Notification: NativeNotification,
    nativeNotificationLifetime: { retain: vi.fn() }, showReminderFallback: fallback };
  const code = ts.transpileModule(`(${initializer.getText(parsed)})`, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
  const notify = runInNewContext(code, context) as (...args: unknown[]) => Promise<string>;
  const onFallback = vi.fn(), onLateFallback = vi.fn();
  return { notifications, fallback, onFallback, onLateFallback,
    notify: (signal: AbortSignal) => notify({ title: "Reminder", body: "Due" }, false, vi.fn(), vi.fn(), onFallback, onLateFallback, signal) };
}

describe("actual native reminder notification", () => {
  it("cancels the ten-second wait and blocks synchronous failed and late show callbacks", async () => {
    vi.useFakeTimers();
    const h = reminderNotificationHarness();
    const controller = new AbortController();
    const pending = h.notify(controller.signal).catch(error => error.message);
    controller.abort();
    expect(await pending).toBe("ASSISTANT_STOPPED");
    expect(h.notifications[0].close).toHaveBeenCalledOnce();
    h.notifications[0].handlers.get("show")?.();
    h.notifications[0].handlers.get("failed")?.();
    expect(h.fallback).not.toHaveBeenCalled();
    expect(h.onFallback).not.toHaveBeenCalled();
    expect(h.onLateFallback).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("does not create a notification after stop already aborted its signal", async () => {
    const h = reminderNotificationHarness();
    const controller = new AbortController();
    controller.abort();
    await expect(h.notify(controller.signal)).rejects.toThrow("ASSISTANT_STOPPED");
    expect(h.notifications).toHaveLength(0);
    expect(h.fallback).not.toHaveBeenCalled();
  });

  it("keeps an acknowledged notification delivered when stop follows show", async () => {
    vi.useFakeTimers();
    const h = reminderNotificationHarness();
    const controller = new AbortController();
    const pending = h.notify(controller.signal);
    h.notifications[0].handlers.get("show")?.();
    controller.abort();
    expect(await pending).toBe("system_notification");
    expect(h.notifications[0].close).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe("actual Electron main shutdown functions", () => {
  it("releases the idle workbench renderer before waiting for backend process exit", async () => {
    const h = harness();
    h.stopMain.mockImplementation(async () => {
      expect(h.closeWindow).toHaveBeenCalledOnce();
      expect(h.closeSession).toHaveBeenCalledOnce();
    });
    await h.tray();
    expect(h.closeWindow).toHaveBeenCalledWith({ deadlineAt: expect.any(Number) });
    expect(h.stopMain).toHaveBeenCalledOnce();
    expect(h.quit).toHaveBeenCalledOnce();
  });

  it("can retry an idle exit after its renderer closed but backend retirement failed", async () => {
    const h = harness();
    h.stopMain.mockRejectedValueOnce(new Error("backend retirement pending"));
    await h.exit();
    expect(h.closeWindow).toHaveBeenCalledOnce();
    expect(h.quit).not.toHaveBeenCalled();
    await h.exit();
    expect(h.stopMain).toHaveBeenCalledTimes(2);
    expect(h.quit).toHaveBeenCalledOnce();
  });

  it("does not close a later workbench when desktop session closure resolves after exit timed out", async () => {
    vi.useFakeTimers();
    const h = harness();
    let release!: () => void;
    h.closeSession.mockImplementation(() => new Promise<void>(resolve => { release = resolve; }));
    const exiting = h.exit();
    await vi.advanceTimersByTimeAsync(30_001);
    await exiting;
    release();
    await vi.advanceTimersByTimeAsync(1);
    expect(h.closeWindow).not.toHaveBeenCalled();
    expect(h.stopMain).not.toHaveBeenCalled();
    expect(h.quit).not.toHaveBeenCalled();
  });

  it("quits an idle tray without a dialog, duplicate stop, or fixed delay", async () => {
    vi.useFakeTimers();
    const h = harness();
    await h.tray();
    expect(h.dialog).not.toHaveBeenCalled();
    expect(h.stopMain).toHaveBeenCalledExactlyOnceWith(false, expect.anything());
    expect(h.quit).toHaveBeenCalledOnce();
    expect(h.context.trayQuitAllInFlight).toBe(false);
  });

  it("finishes explicit idle exit even when the migration-only idle lease is busy", async () => {
    const h = harness();
    h.acquire.mockRejectedValue(new Error("ASSISTANT_LIFECYCLE_BUSY"));
    await h.tray();
    expect(h.context.stopLauncherAssistant).toHaveBeenCalledOnce();
    expect(h.acquire).not.toHaveBeenCalled();
    expect(h.dialog).not.toHaveBeenCalled();
    expect(h.stopMain).toHaveBeenCalledExactlyOnceWith(false, expect.anything());
    expect(h.quit).toHaveBeenCalledOnce();
  });

  it("keeps all producers running when the user cancels", async () => {
    const h = harness();
    h.workspace.state = "active"; h.workspace.count = 2;
    await expect(h.exit()).resolves.toMatchObject({ allowed: false, reason: "operator_cancelled" });
    expect(h.dialog).toHaveBeenCalledOnce();
    expect(h.context.stopLauncherAssistant).not.toHaveBeenCalled();
    expect(h.acquire).not.toHaveBeenCalled();
    expect(h.stopMain).not.toHaveBeenCalled();
    expect(h.stopIsolated).not.toHaveBeenCalled();
    expect(h.closeSession).not.toHaveBeenCalled();
    expect(h.quit).not.toHaveBeenCalled();
  });

  it("starts a fresh execution budget after a minute reading the dialog", async () => {
    vi.useFakeTimers();
    const h = harness();
    h.workspace.state = "active";
    let confirm!: (value: { response: number }) => void;
    h.dialog.mockImplementation(() => new Promise(resolve => { confirm = resolve; }));
    const pending = h.exit();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(h.stopMain).not.toHaveBeenCalled();
    confirm({ response: 1 });
    await expect(pending).resolves.toMatchObject({ allowed: true, reason: "operator_confirmed" });
    expect(h.stopMain).toHaveBeenCalledExactlyOnceWith(true, expect.anything());
    expect(h.quit).toHaveBeenCalledOnce();
  });

  it("can retry after the assistant stopped but the project stop failed", async () => {
    const h = harness();
    h.workspace.state = "active";
    h.dialog.mockResolvedValue({ response: 1 });
    h.stopMain.mockRejectedValueOnce(new Error("project stop incomplete"));
    await h.exit();
    expect(h.context.launcherAssistantExitReady).toBe(true);
    expect(h.quit).not.toHaveBeenCalled();
    h.workspace.state = "idle";
    await h.exit(false);
    expect(h.acquire).not.toHaveBeenCalled();
    expect(h.dialog).toHaveBeenCalledOnce();
    expect(h.quit).toHaveBeenCalledOnce();
    expect(h.stopMain).toHaveBeenCalledTimes(2);
  });

  it("releases an idle assistant lease that arrives after the execution timeout", async () => {
    vi.useFakeTimers();
    const h = harness();
    let resolveLease!: (value: { release: typeof h.release; commit: () => void }) => void;
    h.acquire.mockImplementation(() => new Promise(resolve => { resolveLease = resolve; }));
    const pending = h.exit(false);
    await vi.advanceTimersByTimeAsync(30_000);
    await pending;
    expect(h.quit).not.toHaveBeenCalled();
    resolveLease({ release: h.release, commit: vi.fn() });
    await vi.advanceTimersByTimeAsync(0);
    expect(h.release).toHaveBeenCalledOnce();
    expect(h.stopMain).not.toHaveBeenCalled();
  });

  it("does not stop projects when an explicit assistant stop finishes after timeout", async () => {
    vi.useFakeTimers();
    const h = harness();
    let finishStop!: () => void;
    h.context.stopLauncherAssistant.mockImplementation(() => new Promise(resolve => { finishStop = resolve; }));
    const pending = h.tray();
    await vi.advanceTimersByTimeAsync(30_000);
    await pending;
    finishStop();
    await vi.advanceTimersByTimeAsync(0);
    expect(h.stopIsolated).not.toHaveBeenCalled();
    expect(h.stopMain).not.toHaveBeenCalled();
    expect(h.closeSession).not.toHaveBeenCalled();
    expect(h.quit).not.toHaveBeenCalled();
  });
});
