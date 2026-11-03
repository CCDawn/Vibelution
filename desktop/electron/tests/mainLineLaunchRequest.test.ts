import { mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { randomUUID } from "node:crypto";
import { runInNewContext } from "node:vm";
import { createSourceFile, isFunctionDeclaration, ScriptTarget, transpileModule } from "typescript";
import { afterEach, describe, expect, it, vi } from "vitest";
import { beginLaunchRequestReceipt, type LaunchRequestReceipt } from "../src/lifecycle/launchRequestReceipt.js";
import { normalizeInstanceKey } from "../src/lifecycle/projectStoragePaths.js";
import { executeMainLineWorkbench } from "../src/process/workbenchBackend.js";
import { LauncherLifecycleSupervisor } from "../src/lifecycle/launcherLifecycleSupervisor.js";

const roots: string[] = [];
afterEach(() => { for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }); });
const source = createSourceFile("main.ts", readFileSync(new URL("../src/main.ts", import.meta.url), "utf8"), ScriptTarget.ES2022, true);
const names = ["handleMainLineLaunchRequest", "orchestrateLauncherLifecycleImpl", "openWorkbenchAfterLifecycleReady"];
const code = transpileModule(source.statements.filter(statement => isFunctionDeclaration(statement)
  && names.includes(statement.name?.text || "")).map(statement => statement.getText(source)).join("\n")
  + "\nglobalThis.handleRequest = handleMainLineLaunchRequest; globalThis.lifecycle = orchestrateLauncherLifecycleImpl;", {
  compilerOptions: { target: ScriptTarget.ES2022 }
}).outputText;

function harness() {
  const root = mkdtempSync(join(tmpdir(), "vibelution-main-request-")); roots.push(root);
  const requestId = `launch_${randomUUID().replaceAll("-", "")}`;
  const metadata = { launchRequestId: requestId, workspaceRoot: root };
  const path = join(root, ".runtime", "launcher", "launch-requests", `${requestId}.json`);
  const lease = { instanceId: "main", signal: new AbortController().signal };
  const supervisor = {
    beginIntentWithOptions: vi.fn(() => ({ outcome: "acquired", lease })), clearSlotIfCurrent: vi.fn(),
    isCurrent: vi.fn(() => true), bindCommand: () => lease,
    executeMutation: vi.fn(async () => ({ outcome: "settled", value: { schemaVersion: 1, accepted: true, operation: "restart", commandId: "cmd_exact_request" } })),
    trackObservation: (_id: string, operation: () => Promise<unknown>) => operation(),
    claimReady: vi.fn(() => true), completeReady: vi.fn(() => true), releaseReadyClaim: vi.fn()
  };
  const sandbox = {
    beginLaunchRequestReceipt: vi.fn(beginLaunchRequestReceipt), AbortSignal, console, normalizeInstanceKey, realpathSync,
    createDesktopPathsForApp: () => ({ workspaceRoot: root }),
    ensureProjectControlPlane: vi.fn(async () => true), launcherBootstrap: {}, windowProvider: {},
    authorizeLauncherForceLifecycle: vi.fn(async () => undefined),
    desktopEnvironment: () => ({ VIBELUTION_PYTHON_PATH: "pythonw.exe" }),
    normalizeSupervisedLifecycleOperation: (operation: string) => operation,
    desiredStateForLifecycleOperation: () => "open", workbenchFailedCloseHandling: false,
    hasBackgroundWorkbenchRetirement: () => false, mainWorkbenchCloseStore: { currentTransaction: () => null },
    isWorkbenchStartBlockedByClose: () => false, pendingWorkbenchCloseAck: null,
    joinDecisionForLauncherLifecycleStop: () => ({ waitForInFlightRestart: false, joinInFlightRestart: false }),
    launcherLifecycleSupervisor: supervisor, launcherStateStore: { beginMainLifecycle: vi.fn() },
    app: { isPackaged: false }, inspectUnpackagedShell: vi.fn(async () => ({ stale: false })),
    mainLineBackendIsReachable: vi.fn(async () => false),
    shouldRefreshBeforeLifecycle: vi.fn(() => false), shouldInspectDesktopShellBeforeLifecycle: () => false,
    readLauncherStateFile: () => ({ backendPid: 123, backendCreateTime: 45 }), launcherStatePath: () => "state.json",
    WORKBENCH_START_READY_WAIT_MS: 180000, WORKBENCH_REBUILD_READY_WAIT_MS: 180000,
    verifyRestartedServingVersion: vi.fn(async () => ({ ok: true, inspection: { port: 8123 } })),
    rememberLiveWorkbenchUrl: (url: string) => url, workbenchLoopbackUrl: (port: number) => `http://127.0.0.1:${port}`,
    resolveDesktopActionLoopContext: vi.fn(async () => ({})), openWorkbenchAtCurrentLauncherUrl: vi.fn(async () => {}),
    closeWindowIfSupersededByClosedIntent: vi.fn(async () => {}),
    supersededLifecycleResult: (_operation: string, commandId: string) => ({ accepted: false, commandId, code: "lifecycle_intent_superseded" }),
    restartLauncherToLatestBuild: vi.fn(), notifyDesktopTray: vi.fn(),
    lifecycle: undefined as unknown as (...args: unknown[]) => Promise<unknown>,
    orchestrateLauncherLifecycle: undefined as unknown as (...args: unknown[]) => Promise<unknown>,
    handleRequest: undefined as unknown as (command: string, provenance: string,
      data: typeof metadata & { launchRequestOperation?: string; launchRequestHandoffPid?: number },
      receipt?: LaunchRequestReceipt, selectedRoot?: string) => Promise<void>
  };
  runInNewContext(code, sandbox);
  sandbox.orchestrateLauncherLifecycle = (...args) => sandbox.lifecycle(...args.slice(0, 7), undefined, args[7]);
  return { ...sandbox, context: sandbox, root, path, metadata, read: () => JSON.parse(readFileSync(path, "utf8")) };
}

describe("main-line launch request settlement", () => {
  it("rejects another integration checkout without operating the bound owner's project", async () => {
    const input = harness();
    const other = mkdtempSync(join(tmpdir(), "vibelution-other-root-")); roots.push(other);
    await input.handleRequest("restart", "operator", { ...input.metadata, workspaceRoot: other });
    const path = join(other, ".runtime", "launcher", "launch-requests", `${input.metadata.launchRequestId}.json`);
    expect(JSON.parse(readFileSync(path, "utf8"))).toMatchObject({ status: "failed", code: "launcher_workspace_mismatch" });
    expect(input.launcherLifecycleSupervisor.executeMutation).not.toHaveBeenCalled();
    expect(input.verifyRestartedServingVersion).not.toHaveBeenCalled();
  });

  it("also binds the selected root when an existing project-slot receipt is supplied", async () => {
    const input = harness();
    const other = mkdtempSync(join(tmpdir(), "vibelution-other-slot-")); roots.push(other);
    const receipt = beginLaunchRequestReceipt({ shellRoot: input.root, projectRoot: other,
      operation: "restart", requestId: input.metadata.launchRequestId });
    await input.handleRequest("restart", "operator", input.metadata, receipt, other);
    expect(input.read()).toMatchObject({ status: "failed", projectRoot: other, code: "launcher_workspace_mismatch" });
    expect(input.launcherLifecycleSupervisor.executeMutation).not.toHaveBeenCalled();
  });

  it("never executes when durable received admission fails", async () => {
    const input = harness();
    input.beginLaunchRequestReceipt.mockImplementationOnce(() => { throw new Error("LAUNCH_REQUEST_RECEIPT_PERSISTENCE_FAILED: received"); });
    await input.handleRequest("restart", "operator", input.metadata);
    expect(input.ensureProjectControlPlane).not.toHaveBeenCalled();
    expect(input.launcherLifecycleSupervisor.executeMutation).not.toHaveBeenCalled();
  });

  it.each(["restart_queued", "joined_in_flight_restart"])("leaves %s pending without verifying an unchanged backend", async code => {
    const input = harness();
    input.launcherLifecycleSupervisor.executeMutation.mockResolvedValue({ outcome: "settled", value: {
      schemaVersion: 1, accepted: true, operation: "restart", commandId: "cmd_pending_request", code
    } });
    await input.handleRequest("restart", "forwarded", input.metadata);
    expect(input.read()).toMatchObject({ status: "dispatched", commandId: "cmd_pending_request" });
    expect(input.read().completion).toBeUndefined();
    expect(input.verifyRestartedServingVersion).not.toHaveBeenCalled();
    expect(input.openWorkbenchAtCurrentLauncherUrl).not.toHaveBeenCalled();
    expect(input.launcherLifecycleSupervisor.completeReady).not.toHaveBeenCalled();
  });

  it("preserves the real active-work deferred restart contract through the request owner", async () => {
    const input = harness();
    input.launcherLifecycleSupervisor.executeMutation.mockImplementation(async () => ({ outcome: "settled",
      value: await executeMainLineWorkbench({ workspaceRoot: input.root, pythonPath: "pythonw.exe", operation: "restart",
        command: { commandId: "cmd_real_pending", type: "restart", operation: "restart", noBrowser: true },
        listActiveWork: () => [{ kind: "chat_turn", runId: "run-active", sessionId: "session-active", status: "running" }] }) }));
    await input.handleRequest("restart", "forwarded", input.metadata);
    expect(input.read()).toMatchObject({ status: "dispatched", commandId: "cmd_real_pending" });
    expect(input.read().accepted).toBeUndefined();
    expect(input.verifyRestartedServingVersion).not.toHaveBeenCalled();
    expect(input.openWorkbenchAtCurrentLauncherUrl).not.toHaveBeenCalled();
    expect(input.launcherLifecycleSupervisor.completeReady).not.toHaveBeenCalled();
  });

  it("releases a settled pending restart's intent phase so a later stop can begin", async () => {
    const input = harness();
    const supervisor = new LauncherLifecycleSupervisor();
    Object.assign(input.context, { launcherLifecycleSupervisor: supervisor,
      runWorkbenchLifecycle: vi.fn(async () => await executeMainLineWorkbench({
        workspaceRoot: input.root, pythonPath: "pythonw.exe", operation: "restart",
        command: { commandId: "cmd_real_pending", type: "restart", operation: "restart", noBrowser: true },
        listActiveWork: () => [{ kind: "chat_turn", runId: "run-active", sessionId: "session-active", status: "running" }]
      })) });
    await input.handleRequest("restart", "forwarded", input.metadata);
    expect(input.read()).toMatchObject({ status: "dispatched", commandId: "cmd_real_pending" });
    expect(supervisor.snapshot("main")).toMatchObject({ phase: "observing", commandId: "cmd_real_pending" });
    const stop = supervisor.beginIntentWithOptions({ instanceId: "main", operation: "stop", desiredState: "closed" },
      { joinInFlightRestart: true });
    expect(stop.outcome).toBe("begun");
    expect(input.verifyRestartedServingVersion).not.toHaveBeenCalled();
    expect(input.openWorkbenchAtCurrentLauncherUrl).not.toHaveBeenCalled();
  });

  it("reports a pre-queue rejection instead of waiting for an intent", async () => {
    const input = harness();
    input.shouldRefreshBeforeLifecycle.mockReturnValue(true);
    input.restartLauncherToLatestBuild.mockResolvedValue({ accepted: false, code: "active_work_blocked", message: "Task is active." });
    await input.handleRequest("restart", "operator", input.metadata);
    expect(input.read()).toMatchObject({ status: "failed", operation: "restart", code: "active_work_blocked", message: "Task is active." });
    expect(input.launcherLifecycleSupervisor.executeMutation).not.toHaveBeenCalled();
  });

  it("waits for the existing serving identity and window READY before completing this command", async () => {
    const input = harness(); let verify!: (value: { ok: boolean; inspection: { port: number } }) => void;
    input.verifyRestartedServingVersion.mockImplementation(() => new Promise(resolve => { verify = resolve; }));
    const running = input.handleRequest("restart", "operator", input.metadata);
    await vi.waitFor(() => expect(input.read()).toMatchObject({ status: "dispatched", commandId: "cmd_exact_request" }));
    expect(input.launcherLifecycleSupervisor.completeReady).not.toHaveBeenCalled();
    verify({ ok: true, inspection: { port: 8123 } }); await running;
    expect(input.verifyRestartedServingVersion).toHaveBeenCalledWith(expect.objectContaining({ previousBackendIdentity: { pid: 123, createTime: 45 } }));
    expect(input.openWorkbenchAtCurrentLauncherUrl).toHaveBeenCalledOnce();
    expect(input.read()).toMatchObject({ status: "completed", commandId: "cmd_exact_request",
      completion: { commandId: "cmd_exact_request", ownerPid: process.pid, ready: true } });
  });

  it.each(["serving", "window", "superseded"])("does not complete when %s READY fails", async failure => {
    const input = harness();
    if (failure === "serving") input.verifyRestartedServingVersion.mockResolvedValue({ ok: false, inspection: { port: 0 } });
    if (failure === "window") input.openWorkbenchAtCurrentLauncherUrl.mockRejectedValue(new Error("WINDOW_LOAD_FAILED"));
    if (failure === "superseded") input.launcherLifecycleSupervisor.claimReady.mockReturnValue(false);
    await input.handleRequest("restart", "operator", input.metadata);
    expect(input.read().status).toBe("failed");
    expect(input.read().completion).toBeUndefined();
  });

  it("keeps a scheduled replacement as handoff with the original operation", async () => {
    const input = harness(); input.shouldRefreshBeforeLifecycle.mockReturnValue(true);
    input.restartLauncherToLatestBuild.mockImplementation(async (_interrupt, operation, options) => {
      expect(options.launchRequest.launchRequestId).toBe(input.metadata.launchRequestId);
      expect(options.launchRequest.launchRequestOperation).toBe("restart");
      options.launchRequest.receipt.handoff(operation);
      return { accepted: true, operation: "restart-latest-shell" };
    });
    await input.handleRequest("restart", "operator", input.metadata);
    expect(input.read()).toMatchObject({ status: "handoff", operation: "restart", replacementOperation: "restart" });
    expect(input.launcherLifecycleSupervisor.executeMutation).not.toHaveBeenCalled();
    expect(input.read().completion).toBeUndefined();
  });

  it("resumes the same restart on the replacement owner and completes only its READY", async () => {
    const input = harness();
    mkdirSync(join(input.root, ".runtime", "launcher", "launch-requests"), { recursive: true });
    writeFileSync(input.path, JSON.stringify({ schemaVersion: 1, requestId: input.metadata.launchRequestId,
      projectRoot: input.root, operation: "restart", shellPid: 123, status: "handoff", updatedAt: new Date().toISOString() }));
    await input.handleRequest("start", "operator", { ...input.metadata, launchRequestOperation: "restart", launchRequestHandoffPid: 123 });
    expect(input.read()).toMatchObject({ status: "completed", operation: "restart", shellPid: process.pid,
      commandId: "cmd_exact_request", completion: { ready: true, ownerPid: process.pid } });
    expect(input.launcherLifecycleSupervisor.completeReady).toHaveBeenCalledOnce();
  });

  it("never reexecutes an already received request on another owner", async () => {
    const input = harness();
    mkdirSync(join(input.root, ".runtime", "launcher", "launch-requests"), { recursive: true });
    writeFileSync(input.path, JSON.stringify({ schemaVersion: 1, requestId: input.metadata.launchRequestId,
      projectRoot: input.root, operation: "restart", shellPid: 123, status: "received", updatedAt: new Date().toISOString() }));
    await input.handleRequest("restart", "operator", input.metadata);
    expect(input.ensureProjectControlPlane).not.toHaveBeenCalled();
    expect(input.launcherLifecycleSupervisor.executeMutation).not.toHaveBeenCalled();
    expect(input.read()).toMatchObject({ status: "received", shellPid: 123 });
  });
});
