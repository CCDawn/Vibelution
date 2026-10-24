import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
import { ScriptTarget, transpileModule } from "typescript";
import { describe, expect, it, vi } from "vitest";
import { parseDesktopCliArgs } from "../src/cli/desktopCli.js";
import { shouldDeferWorkbenchOpenUntilLifecycleStart } from "../src/process/desktopShellFreshness.js";
import { normalizeInstanceKey } from "../src/lifecycle/projectStoragePaths.js";
import { PROJECT_SLOT_LIFECYCLE_COMMANDS } from "../src/protocol/applyProjectSlot.js";

const mainSourcePath = fileURLToPath(new URL("../src/main.ts", import.meta.url));

describe("Electron main startup sequence", () => {
  it.each([
    { argv: ["--open-workbench", "open"] },
    { argv: ["--open-workbench"] },
    { argv: ["open"] },
  ])("dispatches one startup open for argv $argv", async ({ argv }) => {
    const source = readFileSync(mainSourcePath, "utf8");
    const begin = source.indexOf("const firstLifecycle = String(desktopCliArgs.lifecycleCommand");
    const end = source.indexOf("// T6:", begin);
    expect(begin).toBeGreaterThan(-1);
    expect(end).toBeGreaterThan(begin);
    const desktopCliArgs = parseDesktopCliArgs(argv);
    const open = vi.fn(async () => undefined);
    const sandbox = {
      desktopCliArgs,
      pendingOpenWorkbenchRequest: desktopCliArgs.openWorkbench,
      pendingProjectRoot: "",
      windowProvider: {},
      shouldDeferWorkbenchOpenUntilLifecycleStart,
      startOrFocusWorkbenchFromProductEntryOnShell: open,
      markWorkbenchOpenRequested: vi.fn(),
    };
    await runInNewContext(transpileModule(`(async () => { ${source.slice(begin, end)} })()`, {
      compilerOptions: { target: ScriptTarget.ES2022 },
    }).outputText, sandbox);
    expect(open).toHaveBeenCalledOnce();
  });

  it("uses launch readiness before opening windows and leaves full freshness on the resident watcher", () => {
    const source = readFileSync(mainSourcePath, "utf8");
    const startup = source.slice(source.indexOf("app.whenReady()"));
    const refreshIndex = startup.indexOf("await refreshPackagedDesktopShellIfStale(");
    const bootstrapIndex = startup.indexOf("launcherBootstrap = await bootstrapMainOwnedLauncher(paths, initialWorkbenchUrl)");
    const watcherIndex = startup.indexOf("startPeriodicShellFreshnessWatch()");
    const refresh = source.slice(
      source.indexOf("async function refreshPackagedDesktopShellIfStale("),
      source.indexOf("async function runSmokeAndQuit(")
    );
    const watcher = source.slice(
      source.indexOf("function startPeriodicShellFreshnessWatch("),
      source.indexOf("async function runTrayBranchInstance(")
    );

    expect(refreshIndex).toBeGreaterThan(-1);
    expect(bootstrapIndex).toBeGreaterThan(refreshIndex);
    expect(watcherIndex).toBeGreaterThan(bootstrapIndex);
    expect(refresh).toContain("await inspectCurrentDesktopShellLaunchReadiness()");
    expect(watcher).toContain("await inspectCurrentDesktopShell()");
  });

  it("does not register whenReady reap on a secondary product instance", () => {
    const source = readFileSync(mainSourcePath, "utf8");
    const gateIndex = source.indexOf("const runPrimaryWhenReady = shouldRunDesktopWhenReadyHandlers(");
    const quitIndex = source.indexOf("if (!runPrimaryWhenReady)");
    const approveIndex = source.indexOf("shutdownApproved = true", quitIndex);
    const whenReadyGuardIndex = source.indexOf("if (runPrimaryWhenReady)");
    const reapIndex = source.indexOf("await reapManagedRuntimeOnDesktopStart");

    expect(gateIndex).toBeGreaterThan(0);
    expect(quitIndex).toBeGreaterThan(gateIndex);
    expect(approveIndex).toBeGreaterThan(quitIndex);
    expect(whenReadyGuardIndex).toBeGreaterThan(approveIndex);
    expect(reapIndex).toBeGreaterThan(whenReadyGuardIndex);
    expect(source).toContain("shouldRunDesktopWhenReadyHandlers({");
  });

  it("starts the workbench lifecycle before loading a possibly-dead workbench URL", () => {
    const source = readFileSync(mainSourcePath, "utf8");
    const deferIndex = source.indexOf("shouldDeferWorkbenchOpenUntilLifecycleStart(firstLifecycle)");
    const openIfIndex = source.indexOf(
      "if (pendingOpenWorkbenchRequest && !desktopCliArgs.workbenchCloseCanary && !deferWorkbenchOpen)"
    );
    const pendingProjectIndex = source.indexOf("if (pendingProjectRoot)");
    const applySlotIndex = source.indexOf(
      "await applyPendingProjectSlot(pendingProjectRoot, firstLifecycle, desktopLifecycleProvenance, {"
    );
    const noProjectLifecycleIndex = source.indexOf(
      'else if (firstLifecycle && firstLifecycle !== "status" && windowProvider !== null)'
    );
    const noProjectHandleIndex = source.indexOf(
      "await handleSecondInstanceLifecycleCommand(firstLifecycle, desktopLifecycleProvenance)"
    );

    expect(deferIndex).toBeGreaterThan(0);
    expect(openIfIndex).toBeGreaterThan(deferIndex);
    expect(pendingProjectIndex).toBeGreaterThan(openIfIndex);
    expect(applySlotIndex).toBeGreaterThan(pendingProjectIndex);
    expect(noProjectLifecycleIndex).toBeGreaterThan(applySlotIndex);
    expect(noProjectHandleIndex).toBeGreaterThan(noProjectLifecycleIndex);
    expect(source.slice(pendingProjectIndex, noProjectHandleIndex)).toContain(
      "await applyPendingProjectSlot(pendingProjectRoot, firstLifecycle, desktopLifecycleProvenance, {"
    );
    expect(source.slice(pendingProjectIndex, noProjectHandleIndex)).toContain(
      "} else if (firstLifecycle && firstLifecycle !== \"status\" && windowProvider !== null)"
    );
    expect(source.slice(noProjectLifecycleIndex, noProjectHandleIndex)).toContain(
      "startOrFocusWorkbenchFromProductEntryOnShell()"
    );
    expect(source).toContain("if (deferWorkbenchOpen)");
  });

  it("does not open the Launcher as a startup window fallback", () => {
    const source = readFileSync(mainSourcePath, "utf8");
    const startupIndex = source.indexOf("if (pendingOpenWorkbenchRequest &&");
    const deferIndex = source.indexOf("if (deferWorkbenchOpen)", startupIndex);

    expect(startupIndex).toBeGreaterThan(0);
    expect(deferIndex).toBeGreaterThan(startupIndex);
    expect(source.slice(startupIndex, deferIndex)).not.toContain("openLauncher");
  });
});

describe("initial workbench discovery and shell readiness", () => {
  function deferred<T>() {
    let resolve!: (value: T) => void;
    let reject!: (reason: unknown) => void;
    const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
    return { promise, resolve, reject };
  }

  function harness() {
    const source = readFileSync(mainSourcePath, "utf8");
    const resolver = source.slice(source.indexOf("async function resolveInitialWorkbenchUrl("),
      source.indexOf("async function bootstrapMainOwnedLauncher("));
    const startup = source.slice(source.indexOf("const initialWorkbenchUrlController ="),
      source.indexOf('electronStartupStage = "tray_ready";'));
    const readiness = deferred<boolean>();
    const url = deferred<string>();
    let signal!: AbortSignal;
    const sandbox = {
      AbortController,
      Error,
      console: { warn: vi.fn() },
      paths: { workspaceRoot: "C:/repo" },
      desktopCliArgs: {},
      desktopEnvironment: () => ({ VIBELUTION_PYTHON_PATH: "C:/repo/python.exe" }),
      resolveWorkbenchUrlFromBridge: vi.fn((input: { signal: AbortSignal }) => {
        signal = input.signal;
        signal.addEventListener("abort", () => url.reject(new Error("discovery cancelled")), { once: true });
        return url.promise;
      }),
      thenLifecycleFromDesktopCli: () => "start",
      refreshPackagedDesktopShellIfStale: vi.fn(() => readiness.promise),
      registerPackagedDeepLinks: vi.fn(() => ({})),
      bootstrapMainOwnedLauncher: vi.fn(async (_paths: unknown, pending: Promise<string>) => ({ url: await pending })),
      launcherBootstrap: null as unknown,
    };
    const pending = runInNewContext(transpileModule(`${resolver}\n(async () => { ${startup}\nreturn launcherBootstrap; })()`, {
      compilerOptions: { target: ScriptTarget.ES2022 },
    }).outputText, sandbox) as Promise<unknown>;
    return { ...sandbox, sandbox, readiness, url, pending, signal: () => signal };
  }

  it("starts both reads together but publishes bootstrap only after readiness and discovery", async () => {
    const h = harness();
    expect(h.resolveWorkbenchUrlFromBridge).toHaveBeenCalledOnce();
    expect(h.refreshPackagedDesktopShellIfStale).toHaveBeenCalledOnce();
    expect(h.bootstrapMainOwnedLauncher).not.toHaveBeenCalled();
    h.readiness.resolve(false);
    await new Promise<void>(resolve => setImmediate(resolve));
    expect(h.bootstrapMainOwnedLauncher).toHaveBeenCalledOnce();
    expect(h.sandbox.launcherBootstrap).toBeNull();
    h.url.resolve("http://127.0.0.1:8002/");
    await expect(h.pending).resolves.toEqual({ url: "http://127.0.0.1:8002/" });
    expect(h.signal().aborted).toBe(true);
    expect(h.resolveWorkbenchUrlFromBridge).toHaveBeenCalledOnce();
  });

  it("cancels and drains discovery without publishing an old shell when refresh takes over", async () => {
    const h = harness();
    h.readiness.resolve(true);
    await expect(h.pending).resolves.toBeUndefined();
    expect(h.signal().aborted).toBe(true);
    expect(h.bootstrapMainOwnedLauncher).not.toHaveBeenCalled();
    expect(h.registerPackagedDeepLinks).not.toHaveBeenCalled();
    expect(h.console.warn).not.toHaveBeenCalled();
  });

  it("keeps the readiness error authoritative while retiring pending discovery", async () => {
    const h = harness();
    const failure = new Error("refresh failed");
    h.readiness.reject(failure);
    await expect(h.pending).rejects.toBe(failure);
    expect(h.signal().aborted).toBe(true);
    expect(h.bootstrapMainOwnedLauncher).not.toHaveBeenCalled();
    expect(h.console.warn).not.toHaveBeenCalled();
  });

  it("handles an early discovery rejection and keeps fallback behind readiness", async () => {
    const h = harness();
    h.url.reject(new Error("discovery failed"));
    await new Promise<void>(resolve => setImmediate(resolve));
    expect(h.console.warn).toHaveBeenCalledWith("discovery failed");
    expect(h.bootstrapMainOwnedLauncher).not.toHaveBeenCalled();
    h.readiness.resolve(false);
    await expect(h.pending).resolves.toEqual({ url: "" });
  });
});

describe("main project lifecycle admission", () => {
  function harness() {
    const source = readFileSync(mainSourcePath, "utf8");
    const begin = source.indexOf("async function applyPendingProjectSlot(");
    const end = source.indexOf("if (runPrimaryWhenReady)", begin);
    const receipt = { duplicate: false, failed: vi.fn(), dispatched: vi.fn() };
    const sandbox = {
      Error,
      windowProvider: { openOrFocusWorkbench: vi.fn(), openOrFocusInstanceWorkbench: vi.fn() },
      launcherBootstrap: {},
      pendingProjectRoot: "",
      createDesktopPathsForApp: () => ({ workspaceRoot: "C:/repo" }),
      normalizeInstanceKey,
      PROJECT_SLOT_LIFECYCLE_COMMANDS,
      beginLaunchRequestReceipt: () => receipt,
      orchestrateLauncherLifecycle: vi.fn(async () => ({ accepted: true })),
      launcherStateStore: { refresh: vi.fn(async () => { throw new Error("inventory fallback"); }) },
      notifyDesktopTray: vi.fn(),
    };
    const apply = runInNewContext(transpileModule(`${source.slice(begin, end)}\napplyPendingProjectSlot;`, {
      compilerOptions: { target: ScriptTarget.ES2022 },
    }).outputText, sandbox) as (root: string, command: string, provenance?: string,
      options?: { hiddenPresentation?: boolean }) => Promise<void>;
    return { apply, receipt, ...sandbox };
  }

  it.each([...PROJECT_SLOT_LIFECYCLE_COMMANDS])("admits exact main %s without any inventory or duplicate window open", async command => {
    const h = harness();
    await h.apply("C:/repo/", command, "forwarded");
    expect(h.orchestrateLauncherLifecycle).toHaveBeenCalledWith(command, {
      schemaVersion: 1, path: "project-slot",
    }, "forwarded");
    expect(h.launcherStateStore.refresh).not.toHaveBeenCalled();
    expect(h.windowProvider.openOrFocusWorkbench).not.toHaveBeenCalled();
    expect(h.receipt.dispatched).toHaveBeenCalledOnce();
  });

  it("does not acknowledge a pending or rejected main lifecycle as dispatched", async () => {
    const h = harness();
    let settle!: (value: { accepted: boolean; code: string; message: string }) => void;
    h.orchestrateLauncherLifecycle.mockImplementationOnce(() => new Promise(resolve => { settle = resolve; }));
    const pending = h.apply("C:/repo", "restart");
    expect(h.receipt.dispatched).not.toHaveBeenCalled();
    expect(h.launcherStateStore.refresh).not.toHaveBeenCalled();
    settle({ accepted: false, code: "lifecycle_rejected", message: "admission denied" });
    await pending;
    expect(h.receipt.failed).toHaveBeenCalledWith("lifecycle_rejected", "admission denied");
    expect(h.receipt.dispatched).not.toHaveBeenCalled();
  });

  it("acknowledges a queued restart without bypassing lifecycle readiness", async () => {
    const h = harness();
    h.orchestrateLauncherLifecycle.mockResolvedValueOnce({ accepted: true, ...{ code: "restart_queued" } });
    await h.apply("C:/repo", "restart", "forwarded");
    expect(h.receipt.dispatched).toHaveBeenCalledOnce();
    expect(h.receipt.failed).not.toHaveBeenCalled();
    expect(h.launcherStateStore.refresh).not.toHaveBeenCalled();
    expect(h.windowProvider.openOrFocusWorkbench).not.toHaveBeenCalled();
  });

  it("keeps preparation failures on the existing failed receipt path", async () => {
    const h = harness();
    h.orchestrateLauncherLifecycle.mockRejectedValueOnce(new Error("admission failed"));
    await h.apply("C:/repo", "start");
    expect(h.receipt.failed).toHaveBeenCalledWith("launch_preparation_failed", "admission failed");
    expect(h.receipt.dispatched).not.toHaveBeenCalled();
  });

  it.each([
    { root: "C:/repo/.worktrees/task", command: "start" },
    { root: "C:/repo-other", command: "start" },
    { root: "C:/repo", command: "status" },
    { root: "C:/repo", command: "toggle" },
    { root: "C:/repo", command: "" },
    { root: "C:/repo", command: "start", hiddenPresentation: true },
  ])("retains registered inventory routing for $root $command", async ({ root, command, hiddenPresentation }) => {
    const h = harness();
    await h.apply(root, command, "operator", { hiddenPresentation });
    expect(h.orchestrateLauncherLifecycle).not.toHaveBeenCalled();
    expect(h.launcherStateStore.refresh).toHaveBeenCalledWith("project_slot");
  });
});

describe("passive startup inventory", () => {
  it.each(["open", "start", ""])("waits for the initial %s dispatch before installing hints and scanning", async command => {
    const source = readFileSync(mainSourcePath, "utf8");
    const startup = source.indexOf("app.whenReady()");
    const begin = source.indexOf("const firstLifecycle = String(desktopCliArgs.lifecycleCommand", startup);
    const end = source.indexOf("// T6:", begin);
    const finallyStart = source.indexOf(".finally(() => {", end);
    const finallyEnd = source.indexOf(".catch(async", finallyStart);
    const beforeDispatch = source.slice(startup, begin);
    expect(beforeDispatch).not.toContain("startLauncherStateFileHints(paths)");
    expect(beforeDispatch).not.toContain("scheduleLauncherStatusCliRefresh();");
    let release!: () => void;
    const gate = new Promise<void>(resolve => { release = resolve; });
    const sandbox = {
      desktopCliArgs: parseDesktopCliArgs(command ? [command] : []),
      pendingOpenWorkbenchRequest: false,
      pendingProjectRoot: "",
      windowProvider: {}, launcherBootstrap: {}, shutdownApproved: false,
      app: { isPackaged: true },
      shouldDeferWorkbenchOpenUntilLifecycleStart,
      markWorkbenchOpenRequested: vi.fn(),
      startOrFocusWorkbenchFromProductEntryOnShell: vi.fn(() => gate),
      handleSecondInstanceLifecycleCommand: vi.fn(() => gate),
      desktopLifecycleProvenance: "operator",
      createDesktopPathsForApp: () => ({ workspaceRoot: "C:/repo" }),
      startLauncherStateFileHints: vi.fn(), scheduleLauncherStatusCliRefresh: vi.fn(),
    };
    const pending = runInNewContext(transpileModule(
      `(async () => { ${source.slice(begin, end)} })()${source.slice(finallyStart, finallyEnd)}`, {
        compilerOptions: { target: ScriptTarget.ES2022 },
      }).outputText, sandbox);
    expect(sandbox.scheduleLauncherStatusCliRefresh).not.toHaveBeenCalled();
    release();
    await pending;
    expect(sandbox.startLauncherStateFileHints).toHaveBeenCalledOnce();
    expect(sandbox.scheduleLauncherStatusCliRefresh).toHaveBeenCalledOnce();
  });

  it("keeps the unpackaged release watcher alive after the file hints reset", async () => {
    const source = readFileSync(mainSourcePath, "utf8");
    const startup = source.indexOf("app.whenReady()");
    const begin = source.indexOf(".finally(() => {", startup);
    const end = source.indexOf(".catch(async", begin);
    const order: string[] = [];
    const watcher = {};
    const sandbox = {
      windowProvider: { refreshLauncherIfReleaseChanged: () => { order.push("catchup"); } },
      launcherBootstrap: {}, shutdownApproved: false,
      app: { isPackaged: false }, launcherActiveReleaseWatcher: null,
      createDesktopPathsForApp: () => ({ workspaceRoot: "C:/repo" }),
      join: (...parts: string[]) => parts.join("/"),
      startLauncherStateFileHints: () => { order.push("hints"); },
      startLauncherActiveReleaseWatcher: () => { order.push("release"); return watcher; },
      scheduleLauncherStatusCliRefresh: () => { order.push("refresh"); },
    };
    await runInNewContext(transpileModule(`Promise.resolve()${source.slice(begin, end)}`, {
      compilerOptions: { target: ScriptTarget.ES2022 },
    }).outputText, sandbox);
    expect(order).toEqual(["hints", "release", "catchup", "refresh"]);
    expect(sandbox.launcherActiveReleaseWatcher).toBe(watcher);
  });
});

describe("hidden presentation forwarding", () => {
  const readMainSource = () => readFileSync(mainSourcePath, "utf8");

  it("forwards the CLI hidden flag into the first-launch project slot apply", () => {
    const source = readMainSource();
    const pendingProjectIndex = source.indexOf("if (pendingProjectRoot)");
    const applyCallIndex = source.indexOf(
      "await applyPendingProjectSlot(pendingProjectRoot, firstLifecycle, desktopLifecycleProvenance, {"
    );
    expect(pendingProjectIndex).toBeGreaterThan(0);
    expect(applyCallIndex).toBeGreaterThan(pendingProjectIndex);
    const applyCall = source.slice(applyCallIndex, source.indexOf("});", applyCallIndex) + 3);
    expect(applyCall).toContain(
      "hiddenPresentation: desktopCliArgs.hiddenPresentation"
    );
    expect(applyCall).toContain("launchRequestId: desktopCliArgs.launchRequestId");
  });

  it("carries hidden presentation on second-instance apply_project intents", () => {
    const source = readMainSource();
    expect(source).toContain("hiddenPresentation: secondCli.hiddenPresentation");
    expect(source).toContain("hiddenPresentation: intent.hiddenPresentation");
  });

  it("marks the branch-instance isolated start request and instance window as hidden on demand", () => {
    const source = readMainSource();
    const parseIndex = source.indexOf("const hiddenPresentation = bodyRecord?.hiddenPresentation === true;");
    const providerCallIndex = source.indexOf(
      "await provider.openOrFocusInstanceWorkbench({"
    );
    expect(parseIndex).toBeGreaterThan(0);
    expect(providerCallIndex).toBeGreaterThan(parseIndex);
    expect(source.slice(providerCallIndex, providerCallIndex + 200)).toContain(
      "...(hiddenPresentation ? { present: false } : {})"
    );
  });

  it("gates every provider present:false call site behind the hidden intent", () => {
    const source = readMainSource();
    const occurrences = source.split("present: false").length - 1;
    const gated = source.split("...(hiddenPresentation ? { present: false } : {})").length - 1;
    expect(occurrences).toBeGreaterThan(0);
    expect(gated).toBe(occurrences);
  });
});
