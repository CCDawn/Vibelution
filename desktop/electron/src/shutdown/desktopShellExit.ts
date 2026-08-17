import type { RuntimeSceneElectronEvent } from "../lifecycle/runtimeSceneBridge.js";
import type { LauncherServiceStopResult } from "../process/launcherServiceClient.js";
import type { ShutdownDecision } from "./shutdownCoordinator.js";

export const DESKTOP_SHELL_EXIT_STEP_TIMEOUT_MS = 8_000;
export const DESKTOP_SHELL_EXIT_BUDGET_MS = 15_000;

export type ApprovedDesktopShellShutdownInput = {
  decision: ShutdownDecision;
  closeDesktopSession: () => Promise<void>;
  recordEvent: (event: RuntimeSceneElectronEvent) => Promise<void>;
  stopManagedRuntime: () => Promise<void>;
  stopPythonLauncher: () => Promise<LauncherServiceStopResult>;
  approveShutdown: () => void;
  stopDesktopActionLoop: () => void;
  quitApp: () => void;
  stepTimeoutMs?: number;
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
  operation: Promise<T>,
  timeoutMs: number,
  label: string
): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | null = null;
  try {
    return await Promise.race([
      operation,
      new Promise<never>((_resolve, reject) => {
        timer = setTimeout(() => {
          reject(new Error(`${label} timed out after ${timeoutMs}ms`));
        }, Math.max(1, Math.round(timeoutMs)));
      })
    ]);
  } finally {
    if (timer !== null) {
      clearTimeout(timer);
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

  const stepTimeoutMs = input.stepTimeoutMs ?? DESKTOP_SHELL_EXIT_STEP_TIMEOUT_MS;
  try {
    await withDesktopShellExitTimeout(input.closeDesktopSession(), stepTimeoutMs, "close desktop session");
  } catch {
    // Fail-open: session close must not block Electron from quitting.
  }

  let stopResult: LauncherServiceStopResult | null = null;
  let stopError = "";
  let managedRuntimeError = "";
  await input.recordEvent({
    eventCode: "electron.runtime.stop_requested",
    message: "Managed project process tree stop requested before desktop shell quit.",
    fields: {}
  }).catch(() => undefined);
  try {
    await withDesktopShellExitTimeout(input.stopManagedRuntime(), stepTimeoutMs, "stop managed runtime");
  } catch (error: unknown) {
    managedRuntimeError = error instanceof Error ? error.message : String(error);
    await input.recordEvent({
      eventCode: "electron.runtime.stop_failed",
      message: "Managed project process tree stop failed before shell quit.",
      fields: { error: managedRuntimeError.slice(0, 500) }
    }).catch(() => undefined);
  }
  if (input.decision.stopPythonLauncher) {
    await input.recordEvent({
      eventCode: "electron.launcher_service.stop_requested",
      message: "Owned Python launcher service stop requested.",
      fields: {}
    }).catch(() => undefined);
    try {
      stopResult = await withDesktopShellExitTimeout(
        input.stopPythonLauncher(),
        stepTimeoutMs,
        "stop python launcher"
      );
    } catch (error: unknown) {
      stopError = error instanceof Error ? error.message : String(error);
      await input.recordEvent({
        eventCode: "electron.launcher_service.stop_failed",
        message: "Owned Python launcher service stop failed before shell quit.",
        fields: { error: stopError.slice(0, 500) }
      }).catch(() => undefined);
    }
  }

  const result: ApprovedDesktopShellShutdownResult = {
    stopManagedRuntime: true,
    managedRuntimeError,
    stopPythonLauncher: input.decision.stopPythonLauncher,
    stopStatus: stopResult?.status ?? (stopError ? "failed" : "not_requested"),
    stoppedPidCount: stopResult?.terminatedPids.length ?? 0,
    stopError
  };

  await input.recordEvent({
    eventCode: "electron.launcher_service.exited",
    message: "Electron desktop shell exit approved.",
    fields: {
      stopManagedRuntime: result.stopManagedRuntime,
      managedRuntimeError: result.managedRuntimeError.slice(0, 500),
      stopPythonLauncher: result.stopPythonLauncher,
      stopStatus: result.stopStatus,
      stoppedPidCount: result.stoppedPidCount
    }
  }).catch(() => undefined);

  // Always fail-open to a real process exit once shutdown was allowed.
  input.approveShutdown();
  input.stopDesktopActionLoop();
  input.quitApp();
  return result;
}
