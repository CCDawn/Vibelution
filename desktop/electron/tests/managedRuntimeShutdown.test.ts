import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
import { transpileModule, ScriptTarget } from "typescript";
import { describe, expect, it, vi } from "vitest";
import { LauncherLifecycleSupervisor } from "../src/lifecycle/launcherLifecycleSupervisor.js";
import { executeApprovedDesktopShellShutdown } from "../src/shutdown/desktopShellExit.js";

describe("managed runtime shutdown admission", () => {
  it.each([false, true])("does not report stopped after a new start takes over (force exit: %s)", async (forceExit) => {
    // Execute the private adapter's real source without booting Electron. The
    // supervisor and exit coordinator remain their production implementations.
    const source = readFileSync(fileURLToPath(new URL("../src/main.ts", import.meta.url)), "utf8");
    const begin = source.indexOf("async function stopManagedRuntime(");
    const end = source.indexOf("\nfunction desktopPythonPath", begin);
    expect(begin).toBeGreaterThan(-1);
    expect(end).toBeGreaterThan(begin);
    const supervisor = new LauncherLifecycleSupervisor();
    let finishStop!: (value: Record<string, unknown>) => void;
    let notifyStarted!: () => void;
    const started = new Promise<void>((resolve) => { notifyStarted = resolve; });
    const backendStop = new Promise<Record<string, unknown>>((resolve) => { finishStop = resolve; });
    const sandbox: Record<string, unknown> = {
      AbortSignal, Error,
      runJoinedMainRuntimeShutdown: (operation: () => Promise<void>) => operation(),
      desktopEnvironment: () => ({ VIBELUTION_PYTHON_PATH: "pythonw.exe" }),
      createDesktopPathsForApp: () => ({ workspaceRoot: "C:/shutdown-test" }),
      launcherBootstrap: null,
      launcherLifecycleSupervisor: supervisor,
      runWorkbenchLifecycle: () => { notifyStarted(); return backendStop; },
      scheduleLauncherStatusCliRefresh: () => undefined
    };
    const script = transpileModule(
      source.slice(begin, end) + "\nglobalThis.stopUnderTest = stopManagedRuntime;",
      { compilerOptions: { target: ScriptTarget.ES2022 } }
    ).outputText;
    runInNewContext(script, sandbox);
    const quit = vi.fn();
    const resultPromise = executeApprovedDesktopShellShutdown({
      decision: { allowed: true, reason: "no_active_work", stopPythonLauncher: false },
      closeDesktopSession: async () => undefined,
      recordEvent: async () => undefined,
      stopManagedRuntime: sandbox.stopUnderTest as (signal: AbortSignal) => Promise<void>,
      stopPythonLauncher: async () => { throw new Error("not requested"); },
      approveShutdown: () => undefined,
      stopDesktopActionLoop: () => undefined,
      quitApp: quit,
      forceExitOnStopFailure: forceExit
    });
    await started;
    supervisor.beginIntent({ instanceId: "main", operation: "start", desiredState: "open" });
    finishStop({ schemaVersion: 1, accepted: true, operation: "shutdown", commandId: "old-stop" });
    const result = await resultPromise;
    expect(result?.stopManagedRuntime).toBe(false);
    expect(result?.managedRuntimeError).toContain("superseded");
    expect(quit).toHaveBeenCalledTimes(forceExit ? 1 : 0);
  });
});
