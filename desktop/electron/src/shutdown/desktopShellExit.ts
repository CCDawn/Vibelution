import type { RuntimeSceneElectronEvent } from "../lifecycle/runtimeSceneBridge.js";
import type { LauncherServiceStopResult } from "../process/launcherServiceClient.js";
import type { ShutdownDecision } from "./shutdownCoordinator.js";

export type ApprovedDesktopShellShutdownInput = {
  decision: ShutdownDecision;
  closeDesktopSession: () => Promise<void>;
  recordEvent: (event: RuntimeSceneElectronEvent) => Promise<void>;
  stopPythonLauncher: () => Promise<LauncherServiceStopResult>;
  approveShutdown: () => void;
  stopDesktopActionLoop: () => void;
  quitApp: () => void;
};

export async function executeApprovedDesktopShellShutdown(input: ApprovedDesktopShellShutdownInput): Promise<void> {
  if (!input.decision.allowed) {
    return;
  }

  await input.closeDesktopSession();
  let stopResult: LauncherServiceStopResult | null = null;
  let stopError = "";
  if (input.decision.stopPythonLauncher) {
    await input.recordEvent({
      eventCode: "electron.launcher_service.stop_requested",
      message: "Owned Python launcher service stop requested.",
      fields: {}
    });
    try {
      stopResult = await input.stopPythonLauncher();
    } catch (error: unknown) {
      stopError = error instanceof Error ? error.message : String(error);
      await input.recordEvent({
        eventCode: "electron.launcher_service.stop_failed",
        message: "Owned Python launcher service stop failed before shell quit.",
        fields: { error: stopError.slice(0, 500) }
      });
    }
  }

  await input.recordEvent({
    eventCode: "electron.launcher_service.exited",
    message: "Electron desktop shell exit approved.",
    fields: {
      stopPythonLauncher: input.decision.stopPythonLauncher,
      stopStatus: stopResult?.status ?? (stopError ? "failed" : "not_requested"),
      stoppedPidCount: stopResult?.terminatedPids.length ?? 0
    }
  });
  input.approveShutdown();
  input.stopDesktopActionLoop();
  input.quitApp();
}
