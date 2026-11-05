import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import ts from "typescript";
import { afterEach, describe, expect, it, vi } from "vitest";
import { acquireAssistantLifecycleLease, combineAssistantActiveWork } from "../src/assistant/lifecycleGuard.js";
import { DesktopLifecycleCoordinator } from "../src/lifecycle/desktopLifecycleCoordinator.js";
import { hideDesktopShellWindowsForExit } from "../src/shutdown/exitWindowPresentation.js";
import { createDesktopShellExitDeadline, executeApprovedDesktopShellShutdown, withDesktopShellExitTimeout } from "../src/shutdown/desktopShellExit.js";
import { decideShutdown, executeShutdownAuthorizationBoundary, resolveQuitActiveWorkStatus, type ActiveWorkStatus, type ShutdownDecision } from "../src/shutdown/shutdownCoordinator.js";
import { projectBranchInstanceStates } from "../src/state/launcherStateStore.js";
import { classifyTrayBranchInstances } from "../src/protocol/launcherControlClient.js";
import { captureShutdownInstanceIds, captureRunningInstanceIds, registryEntriesToShutdownInstanceSnapshots, isVerifiedClosedBranchInventory } from "../src/tray/trayRestartAllCoordinator.js";

const source = readFileSync(new URL("../src/main.ts", import.meta.url), "utf8");
const parsed = ts.createSourceFile("main.ts", source, ts.ScriptTarget.ES2022, true);
const names = ["confirmDesktopShellExit", "requestDesktopShellExit", "residentAssistantStatus",
  "residentAssistantActiveWork", "acquireResidentAssistantShutdownGuard", "runTrayStopAll", "captureShutdownIsolatedInstanceIds"];
const declarations = names.map(name => {
  const declaration = parsed.statements.find(statement => ts.isFunctionDeclaration(statement) && statement.name?.text === name);
  if (!declaration) throw new Error(`Missing main function ${name}`);
  return declaration.getText(parsed);
}).join("\n");

function harness() {
  const workspace: ActiveWorkStatus = { state: "idle", message: "" };
  const shellWindows = [true, true, false].map(visible => {
    const state = { visible, destroyed: false };
    return {
      state,
      isDestroyed: () => state.destroyed,
      isVisible: () => state.visible,
      isMinimized: () => false,
      hide: vi.fn(() => { state.visible = false; }),
      showInactive: vi.fn(() => { state.visible = true; }),
      minimize: vi.fn(),
    };
  });
  let hostState = "ready";
  const release = vi.fn(async () => undefined);
  const commit = vi.fn();
  const acquire = vi.fn(async (_signal?: AbortSignal) => {
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
    AbortSignal, Date, Error, Promise, setTimeout, clearTimeout,
    console: { warn: vi.fn() },
    DESKTOP_QUIT_TOTAL_BUDGET_MS: 30_000,
    QUIT_ACTIVE_WORK_STATUS_TIMEOUT_MS: 8_000,
    ASSISTANT_START_SETTLE_WAIT_MS: 5_000,
    IDLE_ASSISTANT_SHUTDOWN_PROBE_MS: 500,
    launcherBootstrap: { mode: "attached" },
    launcherStateStore: { snapshot: vi.fn(() => ({ instances: [] as unknown[] })),
      refresh: vi.fn(async (_reason: string) => ({ instances: [] as unknown[] })) },
    orchestrateLauncherApi: vi.fn(async (_path: string, _payload: unknown, _signal?: AbortSignal) => ({ items: [] as unknown[] })),
    readRegistry: vi.fn(async (_path: string) => ({ instances: {} })),
    instancesRegistryPath: () => "registry.json",
    knownPidIsAlive: () => true,
    currentLauncherWindowTruth: vi.fn(() => ({ workbench: null,
      instances: [] as { instanceId: string; open: boolean; rendererProcessId: number }[] })),
    projectBranchInstanceStates, classifyTrayBranchInstances,
    captureShutdownInstanceIds, captureRunningInstanceIds, registryEntriesToShutdownInstanceSnapshots, isVerifiedClosedBranchInventory,
    resolveTrayControlContextOrLoopback: async () => ({}),
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
    hideDesktopShellWindowsForExit,
    BrowserWindow: { getAllWindows: () => shellWindows },
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
    launcherAssistantStartupAbort: new AbortController(),
    resumeLauncherAssistantAfterCancelledExit: vi.fn(async () => undefined),
    stopLauncherAssistant: vi.fn(async () => {
      hostState = "stopped";
      context.launcherAssistantExitReady = true;
      context.launcherAssistantStartupAbort.abort();
    }),
  };
  runInNewContext(ts.transpileModule(declarations, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText, context);
  const actions = context as typeof context & {
    requestDesktopShellExit: (reason: string, confirm: boolean) => Promise<ShutdownDecision>;
    runTrayStopAll: () => Promise<void>;
    captureShutdownIsolatedInstanceIds: (deadline: ReturnType<typeof createDesktopShellExitDeadline>) => Promise<string[]>;
  };
  return { context, workspace, shellWindows, release, commit, acquire, stopMain, stopIsolated, closeSession, closeWindow, dialog, quit,
    exit: (operatorRequested = true) => actions.requestDesktopShellExit("desktop_shell_quit", operatorRequested),
    capture: async () => {
      const deadline = createDesktopShellExitDeadline();
      try { return await actions.captureShutdownIsolatedInstanceIds(deadline); }
      finally { deadline.dispose(); }
    },
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
  it("hides the shell before preparing shutdown and keeps it hidden while backend work drains", async () => {
    const h = harness();
    let finishIsolated!: () => void;
    h.acquire.mockImplementation(async () => {
      expect(h.shellWindows.map(window => window.state.visible)).toEqual([false, false, false]);
      return { release: h.release, commit: h.commit };
    });
    h.stopIsolated.mockImplementation(() => new Promise(resolve => { finishIsolated = resolve; }));
    const exiting = h.exit();
    await vi.waitFor(() => expect(h.stopIsolated).toHaveBeenCalledOnce());
    expect(h.shellWindows.slice(0, 2).every(window => window.hide.mock.calls.length === 1)).toBe(true);
    expect(h.shellWindows[2].hide).not.toHaveBeenCalled();
    expect(h.quit).not.toHaveBeenCalled();
    finishIsolated();
    await exiting;
    expect(h.quit).toHaveBeenCalledOnce();
    expect(h.shellWindows.every(window => window.showInactive.mock.calls.length === 0)).toBe(true);
  });

  it("keeps windows visible while authorization is pending and when the operator cancels", async () => {
    const h = harness();
    let finishProbe!: (status: ActiveWorkStatus) => void;
    h.context.fetchLauncherActiveWorkStatus = () => new Promise(resolve => { finishProbe = resolve; });
    const exiting = h.exit();
    await vi.waitFor(() => expect(finishProbe).toBeTypeOf("function"));
    expect(h.shellWindows.every(window => window.hide.mock.calls.length === 0)).toBe(true);
    finishProbe({ state: "active", count: 1, message: "active task" });
    expect((await exiting).reason).toBe("operator_cancelled");
    expect(h.shellWindows.map(window => window.state.visible)).toEqual([true, true, false]);
    expect(h.shellWindows.every(window => window.hide.mock.calls.length === 0)).toBe(true);
    expect(h.quit).not.toHaveBeenCalled();
  });

  it("does not hide windows for an automatic exit refused by active work", async () => {
    const h = harness();
    h.workspace.state = "active";
    expect((await h.exit(false)).allowed).toBe(false);
    expect(h.shellWindows.every(window => window.hide.mock.calls.length === 0)).toBe(true);
    expect(h.dialog).not.toHaveBeenCalled();
  });

  it("restores surviving originally visible windows after shutdown fails", async () => {
    const h = harness();
    h.stopIsolated.mockImplementation(async () => {
      expect(h.shellWindows[0].state.visible).toBe(false);
      h.shellWindows[1].state.destroyed = true;
      throw new Error("isolated runtime did not stop");
    });
    await h.exit();
    expect(h.shellWindows[0].state.visible).toBe(true);
    expect(h.shellWindows[0].showInactive).toHaveBeenCalledOnce();
    expect(h.shellWindows[1].showInactive).not.toHaveBeenCalled();
    expect(h.shellWindows[2].showInactive).not.toHaveBeenCalled();
    expect(h.quit).not.toHaveBeenCalled();
  });

  it("restores windows at the exit deadline even if an assistant stop has not settled", async () => {
    vi.useFakeTimers();
    const h = harness();
    h.acquire.mockRejectedValue(new Error("ASSISTANT_LIFECYCLE_BUSY"));
    let finishStop!: () => void;
    h.context.stopLauncherAssistant.mockImplementation(() => new Promise(resolve => { finishStop = resolve; }));
    const exiting = h.exit();
    await vi.advanceTimersByTimeAsync(1);
    expect(h.shellWindows.map(window => window.state.visible)).toEqual([false, false, false]);
    await vi.advanceTimersByTimeAsync(30_000);
    await exiting;
    expect(h.shellWindows.map(window => window.state.visible)).toEqual([true, true, false]);
    expect(h.quit).not.toHaveBeenCalled();
    finishStop();
    await vi.advanceTimersByTimeAsync(0);
    expect(h.shellWindows[0].showInactive).toHaveBeenCalledOnce();
    expect(h.shellWindows[0].state.visible).toBe(true);
  });

  it("skips full workspace and cleanup refresh when fresh inventories prove every isolated row closed", async () => {
    const h = harness();
    h.context.orchestrateLauncherApi.mockResolvedValue({ items: [
      { id: "worktree:closed", kind: "worktree", current: false, alive: false, checkedOut: true,
        pids: { backend: 0, window: 0, manager: 0 }, runtime: { observedState: "closed", phase: "steady", desiredState: "closed",
          backend: { pid: 0, alive: false, healthy: false, listening: false, portConflict: false }, window: { pid: 0, open: false } } }
    ] });
    expect(await h.capture()).toEqual([]);
    expect(h.context.orchestrateLauncherApi).toHaveBeenCalledOnce();
    expect(h.context.readRegistry).toHaveBeenCalledOnce();
    expect(h.context.launcherStateStore.refresh).not.toHaveBeenCalled();
  });

  it.each(["open", "starting"])("refreshes target-root material for a newly discovered %s row", async state => {
    const h = harness();
    h.context.orchestrateLauncherApi.mockResolvedValue({ items: [
      { id: "worktree:new", path: "D:/new-checkout", checkedOut: true,
        runtime: { observedState: state, phase: state === "starting" ? "building" : "steady", desiredState: "open", backend: { pid: state === "open" ? 12 : 0 } } }
    ] });
    expect(await h.capture()).toContain("worktree:new");
    expect(h.context.launcherStateStore.refresh).toHaveBeenCalledExactlyOnceWith("desktop_shell_exit");
  });

  it("keeps canonical registry transitional rows in the stop inventory", async () => {
    const h = harness();
    h.context.readRegistry.mockResolvedValue({ instances: {
      "worktree:starting": { status: "starting", phase: "building", desiredState: "open", spawnPid: 0 }
    } });
    expect(await h.capture()).toContain("worktree:starting");
    expect(h.context.launcherStateStore.refresh).toHaveBeenCalledOnce();
  });

  it("falls back to full refresh when a live source is unavailable", async () => {
    const h = harness();
    h.context.readRegistry.mockRejectedValue(new Error("registry read failed"));
    await h.capture();
    expect(h.context.launcherStateStore.refresh).toHaveBeenCalledOnce();
  });

  it("does not fast-exit an unlisted native isolated window", async () => {
    const h = harness();
    h.context.currentLauncherWindowTruth.mockReturnValue({ workbench: null, instances: [
      { instanceId: "worktree:unlisted-window", open: true, rendererProcessId: 23 }
    ] });
    await h.capture();
    expect(h.context.launcherStateStore.refresh).toHaveBeenCalledOnce();
  });

  it("does not treat malformed inventory rows as a verified empty inventory", async () => {
    const h = harness();
    h.context.orchestrateLauncherApi.mockResolvedValue({ items: [{}] });
    await h.capture();
    expect(h.context.launcherStateStore.refresh).toHaveBeenCalledOnce();
  });

  it("reconciles a stale cached live row before dropping it from the inventory", async () => {
    const h = harness();
    h.context.launcherStateStore.snapshot.mockReturnValue({ instances: [
      { id: "worktree:old", observedState: "closed", phase: "steady", pid: 42, port: 0, window: { open: false } }
    ] });
    expect(await h.capture()).toEqual([]);
    expect(h.context.launcherStateStore.refresh).toHaveBeenCalledOnce();
  });

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

  it("overlaps idle process retirement only after committing the assistant barrier", async () => {
    vi.useFakeTimers();
    const h = harness();
    const startedAt = Date.now();
    h.context.stopLauncherAssistant.mockImplementation(async () => {
      expect(h.commit).toHaveBeenCalledOnce();
      await new Promise(resolve => setTimeout(resolve, 3000));
    });
    h.stopMain.mockImplementation(async () => {
      expect(h.commit).toHaveBeenCalledOnce();
      await new Promise(resolve => setTimeout(resolve, 6000));
    });
    const exiting = h.exit();
    await vi.advanceTimersByTimeAsync(0);
    expect(h.stopMain).toHaveBeenCalledOnce();
    expect(h.quit).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(5999);
    expect(h.quit).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    await exiting;
    expect(Date.now() - startedAt).toBe(6000);
    expect(h.quit).toHaveBeenCalledOnce();
    expect(h.commit).toHaveBeenCalledOnce();
    expect(h.release).not.toHaveBeenCalled();
    expect(h.context.recordSupervisorEventFallbackLocally).toHaveBeenCalledWith(expect.objectContaining({
      eventCode: "electron.desktop_shell.assistant_overlap",
      fields: { mode: "parallel", reason: "barrier_committed", probeMs: 0 }
    }));
  });

  it("joins the assistant when the main runtime is already stopped", async () => {
    const h = harness();
    let finishAssistant!: () => void;
    h.context.joinWorkbenchCloseBackendStop = async () => true;
    h.context.stopLauncherAssistant.mockImplementation(() => new Promise(resolve => { finishAssistant = resolve; }));
    const exiting = h.exit();
    await vi.waitFor(() => expect(h.closeSession).toHaveBeenCalledOnce());
    expect(h.stopMain).not.toHaveBeenCalled();
    expect(h.quit).not.toHaveBeenCalled();
    finishAssistant();
    await exiting;
    expect(h.quit).toHaveBeenCalledOnce();
  });

  it("waits for the main retirement after a parallel assistant failure and keeps quit blocked", async () => {
    const h = harness();
    let finishMain!: () => void;
    h.context.stopLauncherAssistant.mockRejectedValue(new Error("ASSISTANT_DRAIN_TIMEOUT"));
    h.stopMain.mockImplementation(() => new Promise(resolve => { finishMain = resolve; }));
    let settled = false;
    const exiting = h.exit().then(() => { settled = true; });
    await vi.waitFor(() => expect(h.stopMain).toHaveBeenCalledOnce());
    expect(settled).toBe(false);
    expect(h.quit).not.toHaveBeenCalled();
    finishMain();
    await exiting;
    expect(h.quit).not.toHaveBeenCalled();
    expect(h.release).not.toHaveBeenCalled();
  });

  it("settles the cancelled acquisition and releases its late lease before serial stop", async () => {
    vi.useFakeTimers();
    const h = harness();
    let finishLease!: (value: { release: typeof h.release; commit: typeof h.commit }) => void;
    h.acquire.mockImplementation(() => new Promise(resolve => { finishLease = resolve; }));
    let finishRelease!: () => void;
    h.release.mockImplementation(() => new Promise(resolve => { finishRelease = resolve; }));
    const exiting = h.exit();
    await vi.advanceTimersByTimeAsync(500);
    expect(h.context.stopLauncherAssistant).not.toHaveBeenCalled();
    expect(h.stopMain).not.toHaveBeenCalled();
    finishLease({ release: h.release, commit: h.commit });
    await vi.advanceTimersByTimeAsync(0);
    expect(h.release).toHaveBeenCalledOnce();
    expect(h.context.stopLauncherAssistant).not.toHaveBeenCalled();
    finishRelease();
    await exiting;
    expect(h.context.stopLauncherAssistant).toHaveBeenCalledOnce();
    expect(h.stopMain).toHaveBeenCalledOnce();
    expect(h.quit).toHaveBeenCalledOnce();
    expect(h.commit).not.toHaveBeenCalled();
    expect(h.context.recordSupervisorEventFallbackLocally).toHaveBeenCalledWith(expect.objectContaining({
      eventCode: "electron.desktop_shell.assistant_overlap",
      fields: { mode: "serial", reason: "probe_timeout", probeMs: 500 }
    }));
  });

  it("releases a real probing barrier before host retirement after a 500ms timeout", async () => {
    vi.useFakeTimers();
    const h = harness();
    let gate = "idle";
    const releaseProducer = vi.fn();
    const admission = { drained: Promise.resolve(), seal: async () => undefined,
      check: vi.fn(), release: releaseProducer, commit: h.commit };
    h.acquire.mockImplementation(signal => acquireAssistantLifecycleLease({
      signal,
      host: {
        snapshot: () => ({ state: "ready", errorCode: null }),
        beginLifecycleAdmission: () => admission,
        migrationBarrier: async operation => {
          if (operation === "prepare") { gate = "probing"; return "probing"; }
          if (operation === "status") {
            await new Promise(resolve => setTimeout(resolve, 600));
            gate = "ready"; return "ready";
          }
          await new Promise(resolve => setTimeout(resolve, 50));
          gate = "idle"; return "idle";
        },
      },
      projects: { beginMigrationTransition: () => ({ drained: Promise.resolve(), release: vi.fn() }) },
      reminders: { tryDrainForLifecycle: async () => undefined, resumeAfterMigration: vi.fn() },
      drainQueues: async () => undefined, current: () => true, reopen: () => true, releaseOwner: vi.fn(),
    }));
    h.context.stopLauncherAssistant.mockImplementation(async () => {
      expect(gate).toBe("idle");
      expect(releaseProducer).toHaveBeenCalledOnce();
    });
    const exiting = h.exit();
    await vi.advanceTimersByTimeAsync(500);
    expect(gate).toBe("probing");
    expect(h.context.stopLauncherAssistant).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(100);
    expect(h.context.stopLauncherAssistant).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(50);
    await exiting;
    expect(h.context.stopLauncherAssistant).toHaveBeenCalledOnce();
    expect(h.commit).not.toHaveBeenCalled();
    expect(h.quit).toHaveBeenCalledOnce();
  });

  it("keeps the host alive if cancelled proof cleanup cannot settle within the exit budget", async () => {
    vi.useFakeTimers();
    const h = harness();
    let finishLease!: (value: { release: typeof h.release; commit: typeof h.commit }) => void;
    h.acquire.mockImplementation(() => new Promise(resolve => { finishLease = resolve; }));
    const exiting = h.exit();
    await vi.advanceTimersByTimeAsync(30_001);
    await exiting;
    expect(h.context.stopLauncherAssistant).not.toHaveBeenCalled();
    expect(h.stopMain).not.toHaveBeenCalled();
    expect(h.closeWindow).not.toHaveBeenCalled();
    expect(h.quit).not.toHaveBeenCalled();
    finishLease({ release: h.release, commit: h.commit });
    await vi.advanceTimersByTimeAsync(0);
    expect(h.release).toHaveBeenCalledOnce();
    expect(h.context.stopLauncherAssistant).not.toHaveBeenCalled();
    expect(h.commit).not.toHaveBeenCalled();
  });

  it("keeps serial retirement when only degraded idle observations are available", async () => {
    const h = harness();
    h.workspace.state = "unobservable";
    const result = await h.exit();
    expect(result).toMatchObject({ allowed: true, reason: "no_active_work_observation_degraded" });
    expect(h.acquire).not.toHaveBeenCalled();
    expect(h.context.stopLauncherAssistant).toHaveBeenCalledOnce();
    expect(h.stopMain).toHaveBeenCalledOnce();
    expect(h.quit).toHaveBeenCalledOnce();
  });

  it("finishes explicit idle exit even when the migration-only idle lease is busy", async () => {
    const h = harness();
    h.acquire.mockRejectedValue(new Error("ASSISTANT_LIFECYCLE_BUSY"));
    await h.tray();
    expect(h.context.stopLauncherAssistant).toHaveBeenCalledOnce();
    expect(h.acquire).toHaveBeenCalledOnce();
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

  it("does not stop projects when an unfenced assistant stop finishes after timeout", async () => {
    vi.useFakeTimers();
    const h = harness();
    h.acquire.mockRejectedValue(new Error("ASSISTANT_LIFECYCLE_BUSY"));
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

  it.each(["acquire", "commit"])("retains serial retirement when the idle barrier fails during %s", async stage => {
    const h = harness();
    if (stage === "acquire") h.acquire.mockRejectedValue(new Error("ASSISTANT_LIFECYCLE_BUSY"));
    else h.commit.mockImplementation(() => { throw new Error("ASSISTANT_LIFECYCLE_UNAVAILABLE"); });
    let finishAssistant!: () => void;
    h.context.stopLauncherAssistant.mockImplementation(() => new Promise(resolve => { finishAssistant = resolve; }));
    const exiting = h.exit();
    await vi.waitFor(() => expect(h.context.stopLauncherAssistant).toHaveBeenCalledOnce());
    expect(h.stopMain).not.toHaveBeenCalled();
    finishAssistant();
    await exiting;
    expect(h.stopMain).toHaveBeenCalledOnce();
    expect(h.quit).toHaveBeenCalledOnce();
    if (stage === "commit") expect(h.release).toHaveBeenCalledOnce();
    expect(h.context.recordSupervisorEventFallbackLocally).toHaveBeenCalledWith(expect.objectContaining({
      eventCode: "electron.desktop_shell.assistant_overlap",
      fields: expect.objectContaining({ mode: "serial", reason: stage === "acquire"
        ? "ASSISTANT_LIFECYCLE_BUSY" : "ASSISTANT_LIFECYCLE_UNAVAILABLE" })
    }));
  });

  it("does not copy unexpected barrier failures into runtime diagnostics", async () => {
    const h = harness();
    h.acquire.mockRejectedValue(new Error("Unexpected private request data"));
    await h.exit();
    const decisions = h.context.recordSupervisorEventFallbackLocally.mock.calls.map(([event]) => event)
      .filter(event => event.eventCode === "electron.desktop_shell.assistant_overlap");
    expect(decisions).toEqual([expect.objectContaining({
      fields: expect.objectContaining({ mode: "serial", reason: "unclassified" })
    })]);
    expect(JSON.stringify(decisions)).not.toContain("Unexpected private request data");
  });

  it("joins assistant retirement after a main stop failure without approving quit", async () => {
    const h = harness();
    let finishAssistant!: () => void;
    h.context.stopLauncherAssistant.mockImplementation(() => new Promise(resolve => { finishAssistant = resolve; }));
    h.stopMain.mockRejectedValue(new Error("main stop failed"));
    let settled = false;
    const exiting = h.exit().then(() => { settled = true; });
    await vi.waitFor(() => expect(h.stopMain).toHaveBeenCalledOnce());
    expect(settled).toBe(false);
    expect(h.quit).not.toHaveBeenCalled();
    finishAssistant();
    await exiting;
    expect(h.quit).not.toHaveBeenCalled();
    expect(h.release).not.toHaveBeenCalled();
  });

  it("keeps quit blocked when guarded assistant retirement misses the execution deadline", async () => {
    vi.useFakeTimers();
    const h = harness();
    let finishAssistant!: () => void;
    h.context.stopLauncherAssistant.mockImplementation(() => new Promise(resolve => { finishAssistant = resolve; }));
    const exiting = h.exit();
    await vi.advanceTimersByTimeAsync(30000);
    await exiting;
    expect(h.stopMain).toHaveBeenCalledOnce();
    expect(h.quit).not.toHaveBeenCalled();
    finishAssistant();
    await vi.advanceTimersByTimeAsync(0);
    expect(h.quit).not.toHaveBeenCalled();
    expect(h.release).not.toHaveBeenCalled();
  });
});
