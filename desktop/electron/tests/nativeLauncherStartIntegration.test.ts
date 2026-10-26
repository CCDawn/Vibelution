import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
import { createSourceFile, isFunctionDeclaration, ScriptTarget, transpileModule } from "typescript";
import { describe, expect, it, vi } from "vitest";

const source = readFileSync(fileURLToPath(new URL("../src/main.ts", import.meta.url)), "utf8");
const start = source.indexOf("async function orchestrateLauncherLifecycle(");
const firstStatement = source.indexOf("  if (launcherBootstrap === null)", start);
const beforeMutation = source.indexOf("  // Claim cancellation before frontend preflight", start);
const preflight = source.slice(firstStatement, beforeMutation);

function sandbox(nativeColdStart = true) {
  const inFlight = { commandId: "cmd_existing_inflight", epoch: 7 };
  const mutate = vi.fn(() => { inFlight.commandId = "changed"; inFlight.epoch += 1; });
  return {
    nativeColdStart, shutdownApproved: false, inFlight, mutate, operation: "start", payload: { path: "start" }, signal: undefined,
    launcherBootstrap: {}, app: { isPackaged: true },
    authorizeLauncherForceLifecycle: vi.fn(async () => undefined),
    desktopEnvironment: () => ({ PYTHON: "pythonw.exe" }),
    normalizeSupervisedLifecycleOperation: (operation: string) => operation,
    desiredStateForLifecycleOperation: () => "open",
    createDesktopPathsForApp: () => ({ workspaceRoot: "C:/project" }),
    mainWorkbenchCloseStore: { currentTransaction: vi.fn((): { phase: string; windowAcknowledged?: boolean } | null => null) },
    hasBackgroundWorkbenchRetirement: vi.fn((_workspaceRoot: string) => false),
    mainLineBackendIsReachable: vi.fn(async () => false),
    inspectCurrentDesktopShellLaunchReadiness: vi.fn(async () => ({ schemaVersion: 1, launchBlocking: false, reason: "current" })),
    launcherLifecycleSupervisor: { beginIntentWithOptions: mutate, intentGeneration: vi.fn(() => 1) },
    launcherStateStore: { beginMainLifecycle: mutate },
    supersededLifecycleResult: (operation: string) => ({ accepted: false, operation, code: "lifecycle_intent_superseded" }),
  };
}

async function runPreflight(context: ReturnType<typeof sandbox>) {
  return await runInNewContext(transpileModule(`(async () => { ${preflight}\n mutate(); return "admitted"; })()`, {
    compilerOptions: { target: ScriptTarget.ES2022 },
  }).outputText, context);
}

describe("Native start uses the original main lifecycle", () => {
  describe.each(["start", "restart"])("pending close admission for %s", (operation) => {
    it.each([
      { phase: "backend_closing", windowAcknowledged: false, pendingOwner: false },
      { phase: "background_closing", windowAcknowledged: true, pendingOwner: false },
      { phase: "window_close_authorized", windowAcknowledged: false, pendingOwner: false },
      { phase: "succeeded", windowAcknowledged: true, pendingOwner: true },
    ])("returns pending before any read-only gate or mutation for $phase / owner pending=$pendingOwner", async ({ phase, windowAcknowledged, pendingOwner }) => {
      const context = sandbox();
      context.operation = operation;
      context.payload.path = operation;
      context.mainWorkbenchCloseStore.currentTransaction.mockReturnValue({ phase, windowAcknowledged });
      context.hasBackgroundWorkbenchRetirement.mockReturnValue(pendingOwner);
      // A reachable retiring backend must never be mistaken for a reusable one.
      context.mainLineBackendIsReachable.mockResolvedValue(true);
      expect(await runPreflight(context)).toMatchObject({ accepted: false, operation, code: "backend_retiring" });
      expect(context.mutate).not.toHaveBeenCalled();
      expect(context.inFlight).toEqual({ commandId: "cmd_existing_inflight", epoch: 7 });
      expect(context.launcherLifecycleSupervisor.intentGeneration).not.toHaveBeenCalled();
      expect(context.mainLineBackendIsReachable).not.toHaveBeenCalled();
      expect(context.inspectCurrentDesktopShellLaunchReadiness).not.toHaveBeenCalled();
    });
  });

  it("runs the native cold-start read-only gate after retirement reaches succeeded", async () => {
    const context = sandbox();
    context.mainWorkbenchCloseStore.currentTransaction.mockReturnValue({ phase: "succeeded", windowAcknowledged: true });
    expect(await runPreflight(context)).toBe("admitted");
    expect(context.inspectCurrentDesktopShellLaunchReadiness).toHaveBeenCalledOnce();
    expect(context.mutate).toHaveBeenCalledOnce();
    expect(context.inFlight.epoch).toBe(8);
  });

  it("rejects shutdown before the first await without reviving through the legacy bridge", async () => {
    const context = sandbox();
    context.shutdownApproved = true;
    await expect(runPreflight(context)).rejects.toThrow("shutting down");
    expect(context.authorizeLauncherForceLifecycle).not.toHaveBeenCalled();
    expect(context.mutate).not.toHaveBeenCalled();
  });

  it("rejects shutdown approved while the read-only gate is in flight", async () => {
    const context = sandbox();
    context.inspectCurrentDesktopShellLaunchReadiness.mockImplementation(async () => {
      context.shutdownApproved = true;
      return { schemaVersion: 1, launchBlocking: false, reason: "current" };
    });
    await expect(runPreflight(context)).rejects.toThrow("shutting down");
    expect(context.mutate).not.toHaveBeenCalled();
  });

  it("proves no dispatch before superseding an existing intent when the shell needs refresh", async () => {
    const context = sandbox();
    context.inspectCurrentDesktopShellLaunchReadiness.mockResolvedValue({ schemaVersion: 1, launchBlocking: true, reason: "old_shell" });
    expect(await runPreflight(context)).toMatchObject({ accepted: false, code: "native_requires_legacy_launch" });
    expect(context.mutate).not.toHaveBeenCalled();
    expect(context.inFlight.commandId).toBe("cmd_existing_inflight");
  });

  it("fails closed without superseding the current intent when the readiness bridge fails", async () => {
    const context = sandbox();
    context.inspectCurrentDesktopShellLaunchReadiness.mockRejectedValue(new Error("readiness unavailable"));
    await expect(runPreflight(context)).rejects.toThrow("readiness unavailable");
    expect(context.mutate).not.toHaveBeenCalled();
  });

  it("leaves live-backend reuse to the compatibility entry without a second inspection", async () => {
    const context = sandbox();
    context.mainLineBackendIsReachable.mockResolvedValue(true);
    expect(await runPreflight(context)).toMatchObject({ accepted: false, code: "native_requires_legacy_launch" });
    expect(context.inspectCurrentDesktopShellLaunchReadiness).not.toHaveBeenCalled();
    expect(context.mutate).not.toHaveBeenCalled();
  });

  it("does not revive a start when a newer stop arrived during its read-only gate", async () => {
    const context = sandbox();
    context.launcherLifecycleSupervisor.intentGeneration.mockReturnValueOnce(1).mockReturnValue(2);
    expect(await runPreflight(context)).toMatchObject({ accepted: false, code: "lifecycle_intent_superseded" });
    expect(context.mutate).not.toHaveBeenCalled();
  });

  it("admits a current cold backend once and retains the original entry behavior", async () => {
    const current = sandbox();
    expect(await runPreflight(current)).toBe("admitted");
    expect(current.inspectCurrentDesktopShellLaunchReadiness).toHaveBeenCalledOnce();
    expect(current.mutate).toHaveBeenCalledOnce();
    const original = sandbox(false);
    expect(await runPreflight(original)).toBe("admitted");
    expect(original.inspectCurrentDesktopShellLaunchReadiness).not.toHaveBeenCalled();
  });

  it("publishes only after real Windows control-plane readiness and retires on direct exit", () => {
    const parsed = createSourceFile("main.ts", source, ScriptTarget.Latest, true);
    const bootstrap = parsed.statements.find(node => isFunctionDeclaration(node) && node.name?.text === "bootstrapProjectControlPlane");
    if (!bootstrap) throw new Error("Missing shared project control-plane bootstrap");
    const startup = bootstrap.getText(parsed);
    const readyIndex = startup.indexOf("resolveLauncherControlPlaneReady?.()");
    const transportIndex = startup.indexOf("await startNativeLauncherStartTransport(");
    expect(readyIndex).toBeGreaterThan(0);
    expect(transportIndex).toBeGreaterThan(readyIndex);
    expect(startup).toContain('app.isPackaged && process.platform === "win32" && process.versions.electron');
    expect(startup).toContain("resolveActiveCanonicalRuntimeHome(paths.workspaceRoot)");
    expect(startup).toContain('app.once("quit", retireTransport)');
    expect(startup).toContain('process.once("exit", retireTransport)');
    const admission = source.indexOf("if (nativeColdStart)", start);
    expect(admission).toBeLessThan(source.indexOf("launcherLifecycleSupervisor.beginIntentWithOptions", start));
    expect(admission).toBeLessThan(source.indexOf("launcherStateStore.beginMainLifecycle", start));
  });
});
