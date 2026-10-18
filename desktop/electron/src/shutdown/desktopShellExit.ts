import type { RuntimeSceneElectronEvent } from "../lifecycle/runtimeSceneBridge.js";
import type { LauncherServiceStopResult } from "../process/launcherServiceClient.js";
import type { ShutdownDecision } from "./shutdownCoordinator.js";

export const DESKTOP_SHELL_EXIT_STEP_TIMEOUT_MS = 8_000;
export const DESKTOP_SHELL_EXIT_BUDGET_MS = 15_000;

export type DesktopShellExitDeadline = {
  budgetMs: number;
  expiresAt: number;
  signal: AbortSignal;
  remainingMs: () => number;
  dispose: () => void;
};

export function createDesktopShellExitDeadline(
  timeoutMs = DESKTOP_SHELL_EXIT_BUDGET_MS,
  now: () => number = Date.now
): DesktopShellExitDeadline {
  const budgetMs = Math.max(1, Math.round(timeoutMs));
  const expiresAt = now() + budgetMs;
  const controller = new AbortController();
  const timer = setTimeout(() => {
    controller.abort(new Error(`desktop shell exit timed out after ${budgetMs}ms`));
  }, budgetMs);
  timer.unref?.();
  return {
    budgetMs,
    expiresAt,
    signal: controller.signal,
    remainingMs: () => Math.max(0, expiresAt - now()),
    dispose: () => clearTimeout(timer)
  };
}

export type ApprovedDesktopShellShutdownInput = {
  decision: ShutdownDecision;
  closeDesktopSession: (signal: AbortSignal) => Promise<void>;
  recordEvent: (event: RuntimeSceneElectronEvent) => void | Promise<void>;
  stopManagedRuntime: (signal: AbortSignal) => Promise<void>;
  stopPythonLauncher: (signal: AbortSignal) => Promise<LauncherServiceStopResult>;
  approveShutdown: () => void;
  stopDesktopActionLoop: () => void;
  quitApp: () => void;
  deadline?: DesktopShellExitDeadline;
  forceExitOnStopFailure?: boolean;
};

export type ApprovedDesktopShellShutdownResult = {
  stopManagedRuntime: boolean;
  managedRuntimeError: string;
  stopPythonLauncher: boolean;
  stopStatus: "stopped" | "skipped" | "failed" | "not_requested";
  stoppedPidCount: number;
  stopError: string;
};

export async function withDesktopShellExitTimeout<T>(
  operation: Promise<T> | ((signal: AbortSignal) => Promise<T>),
  timeout: number | DesktopShellExitDeadline,
  label: string
): Promise<T> {
  const ownsDeadline = typeof timeout === "number";
  const deadline = ownsDeadline ? createDesktopShellExitDeadline(timeout) : timeout;
  const timeoutError = (): Error => new Error(`${label} timed out after ${deadline.budgetMs}ms`);
  let onAbort: (() => void) | null = null;
  try {
    if (deadline.signal.aborted || deadline.remainingMs() <= 0) {
      throw timeoutError();
    }
    const pending = Promise.resolve().then(() =>
      typeof operation === "function" ? operation(deadline.signal) : operation
    );
    return await Promise.race([
      pending,
      new Promise<never>((_resolve, reject) => {
        onAbort = () => reject(timeoutError());
        deadline.signal.addEventListener("abort", onAbort, { once: true });
        if (deadline.signal.aborted) {
          onAbort();
        }
      })
    ]);
  } finally {
    if (onAbort !== null) {
      deadline.signal.removeEventListener("abort", onAbort);
    }
    if (ownsDeadline) {
      deadline.dispose();
    }
  }
}

export type DesktopStartRuntimeReapInput = {
  stopManagedRuntime: () => Promise<void>;
  stopLeftoverPythonLauncher?: () => Promise<LauncherServiceStopResult>;
  recordEvent: (event: RuntimeSceneElectronEvent) => Promise<void>;
  stepTimeoutMs?: number;
};

export type DesktopStartRuntimeReapResult = {
  stopManagedRuntime: boolean;
  managedRuntimeError: string;
  stopLeftoverPythonLauncher: boolean;
  leftoverPythonStopStatus: "stopped" | "skipped" | "failed" | "not_requested";
  leftoverPythonStopError: string;
};

export async function reapManagedRuntimeOnDesktopStart(
  input: DesktopStartRuntimeReapInput
): Promise<DesktopStartRuntimeReapResult> {
  const stepTimeoutMs = input.stepTimeoutMs ?? DESKTOP_SHELL_EXIT_STEP_TIMEOUT_MS;
  let managedRuntimeError = "";
  let leftoverPythonStopError = "";
  let leftoverStopResult: LauncherServiceStopResult | null = null;
  await input
    .recordEvent({
      eventCode: "electron.runtime.start_reap_requested",
      message: "Previous managed project process tree stop requested before desktop shell start.",
      fields: {}
    })
    .catch(() => undefined);
  try {
    await withDesktopShellExitTimeout(input.stopManagedRuntime(), stepTimeoutMs, "reap managed runtime");
  } catch (error: unknown) {
    managedRuntimeError = error instanceof Error ? error.message : String(error);
    await input
      .recordEvent({
        eventCode: "electron.runtime.start_reap_failed",
        message: "Previous managed project process tree stop failed before desktop shell start.",
        fields: { error: managedRuntimeError.slice(0, 500) }
      })
      .catch(() => undefined);
  }
  if (input.stopLeftoverPythonLauncher) {
    await input
      .recordEvent({
        eventCode: "electron.launcher_service.start_reap_requested",
        message: "Leftover Python launcher service stop requested before desktop shell start.",
        fields: {}
      })
      .catch(() => undefined);
    try {
      leftoverStopResult = await withDesktopShellExitTimeout(
        input.stopLeftoverPythonLauncher(),
        stepTimeoutMs,
        "reap leftover python launcher"
      );
    } catch (error: unknown) {
      leftoverPythonStopError = error instanceof Error ? error.message : String(error);
      await input
        .recordEvent({
          eventCode: "electron.launcher_service.start_reap_failed",
          message: "Leftover Python launcher service stop failed before desktop shell start.",
          fields: { error: leftoverPythonStopError.slice(0, 500) }
        })
        .catch(() => undefined);
    }
  }
  return {
    stopManagedRuntime: true,
    managedRuntimeError,
    stopLeftoverPythonLauncher: Boolean(input.stopLeftoverPythonLauncher),
    leftoverPythonStopStatus: leftoverStopResult?.status ?? (leftoverPythonStopError ? "failed" : "not_requested"),
    leftoverPythonStopError
  };
}

export async function executeApprovedDesktopShellShutdown(
  input: ApprovedDesktopShellShutdownInput
): Promise<ApprovedDesktopShellShutdownResult | null> {
  if (!input.decision.allowed) {
    return null;
  }

  const ownsDeadline = input.deadline === undefined;
  const deadline = input.deadline ?? createDesktopShellExitDeadline();
  const startedAt = Date.now();
  let closeSessionMs = 0;
  let managedRuntimeMs = 0;
  let launcherStopMs = 0;
  const record = (event: RuntimeSceneElectronEvent): void => {
    // Main persists shutdown events locally before returning. An asynchronous
    // observer must not hold up the processes whose backend it reports to.
    try {
      void Promise.resolve(input.recordEvent({
        ...event,
        fields: {
          ...event.fields,
          elapsedMs: Math.max(0, Date.now() - startedAt),
          budgetRemainingMs: deadline.remainingMs(),
          closeSessionMs,
          managedRuntimeMs,
          launcherStopMs
        }
      })).catch(() => undefined);
    } catch {
      // Evidence failures cannot change the verified runtime stop outcome.
    }
  };
  try {
    const sessionStartedAt = Date.now();
    try {
      await withDesktopShellExitTimeout(input.closeDesktopSession, deadline, "close desktop session");
    } catch {
      // Fail-open: session close must not block Electron from quitting.
    }
    closeSessionMs = Math.max(0, Date.now() - sessionStartedAt);

    let stopResult: LauncherServiceStopResult | null = null;
    let stopError = "";
    let managedRuntimeError = "";
    record({
      eventCode: "electron.runtime.stop_requested",
      message: "Managed project process tree stop requested before desktop shell quit.",
      fields: {}
    });
    const managedStartedAt = Date.now();
    try {
      await withDesktopShellExitTimeout(input.stopManagedRuntime, deadline, "stop managed runtime");
    } catch (error: unknown) {
      managedRuntimeError = error instanceof Error ? error.message : String(error);
      managedRuntimeMs = Math.max(0, Date.now() - managedStartedAt);
      record({
        eventCode: "electron.runtime.stop_failed",
        message: "Managed project process tree stop failed before shell quit.",
        fields: { error: managedRuntimeError.slice(0, 500) }
      });
    } finally {
      managedRuntimeMs = Math.max(0, Date.now() - managedStartedAt);
    }
    if (input.decision.stopPythonLauncher) {
      record({
        eventCode: "electron.launcher_service.stop_requested",
        message: "Owned Python launcher service stop requested.",
        fields: {}
      });
      const launcherStartedAt = Date.now();
      try {
        stopResult = await withDesktopShellExitTimeout(input.stopPythonLauncher, deadline, "stop python launcher");
      } catch (error: unknown) {
        stopError = error instanceof Error ? error.message : String(error);
        launcherStopMs = Math.max(0, Date.now() - launcherStartedAt);
        record({
          eventCode: "electron.launcher_service.stop_failed",
          message: "Owned Python launcher service stop failed before shell quit.",
          fields: { error: stopError.slice(0, 500) }
        });
      } finally {
        launcherStopMs = Math.max(0, Date.now() - launcherStartedAt);
      }
    }

    const result: ApprovedDesktopShellShutdownResult = {
      stopManagedRuntime: !managedRuntimeError,
      managedRuntimeError,
      stopPythonLauncher: input.decision.stopPythonLauncher,
      stopStatus: stopResult?.status ?? (stopError ? "failed" : "not_requested"),
      stoppedPidCount: stopResult?.terminatedPids.length ?? 0,
      stopError
    };

    if ((managedRuntimeError || stopError) && !input.forceExitOnStopFailure) {
      record({
        eventCode: "electron.desktop_shell.exit_blocked_stop_failed",
        message: "Desktop shell exit was cancelled because managed processes did not stop cleanly.",
        fields: {
          managedRuntimeError: managedRuntimeError.slice(0, 500),
          launcherStopError: stopError.slice(0, 500)
        }
      });
      return result;
    }

    record({
      eventCode: "electron.launcher_service.exited",
      message: "Electron desktop shell exit approved.",
      fields: {
        stopManagedRuntime: result.stopManagedRuntime,
        managedRuntimeError: result.managedRuntimeError.slice(0, 500),
        stopPythonLauncher: result.stopPythonLauncher,
        stopStatus: result.stopStatus,
        stoppedPidCount: result.stoppedPidCount
      }
    });

    input.approveShutdown();
    input.stopDesktopActionLoop();
    input.quitApp();
    return result;
  } finally {
    if (ownsDeadline) {
      deadline.dispose();
    }
  }
}
