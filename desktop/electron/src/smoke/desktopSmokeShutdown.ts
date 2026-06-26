import type { RuntimeSceneElectronEvent } from "../lifecycle/runtimeSceneBridge.js";
import type { LauncherBootstrapResult } from "../process/launcherBootstrap.js";
import type { LauncherServiceStopResult } from "../process/launcherServiceClient.js";
import {
  executeApprovedDesktopShellShutdown,
  type ApprovedDesktopShellShutdownResult
} from "../shutdown/desktopShellExit.js";
import { decideShutdown } from "../shutdown/shutdownCoordinator.js";
import { emptyDesktopSmokeShutdownSummary, type DesktopSmokeShutdownSummary } from "./desktopSmoke.js";

export type DesktopSmokeShutdownInput = {
  bootstrap: LauncherBootstrapResult | null;
  closeDesktopSession: () => Promise<void>;
  recordEvent: (event: RuntimeSceneElectronEvent) => Promise<void>;
  stopPythonLauncher: () => Promise<LauncherServiceStopResult>;
  approveShutdown: () => void;
  stopDesktopActionLoop: () => void;
};

export async function prepareDesktopSmokeShutdown(input: DesktopSmokeShutdownInput): Promise<DesktopSmokeShutdownSummary> {
  if (input.bootstrap === null) {
    return emptyDesktopSmokeShutdownSummary();
  }

  const decision = await decideShutdown({
    ownershipMode: input.bootstrap.mode,
    activeWorkStatus: async () => ({ active: false, message: "" })
  });
  const result = await executeApprovedDesktopShellShutdown({
    decision,
    closeDesktopSession: input.closeDesktopSession,
    recordEvent: input.recordEvent,
    stopPythonLauncher: input.stopPythonLauncher,
    approveShutdown: input.approveShutdown,
    stopDesktopActionLoop: input.stopDesktopActionLoop,
    quitApp: () => {
      // Smoke writes the summary after shutdown, then quits from the caller.
    }
  });
  return desktopSmokeShutdownSummaryFromResult(result);
}

function desktopSmokeShutdownSummaryFromResult(
  result: ApprovedDesktopShellShutdownResult | null
): DesktopSmokeShutdownSummary {
  if (result === null) {
    return emptyDesktopSmokeShutdownSummary();
  }
  return {
    attempted: true,
    stopPythonLauncher: result.stopPythonLauncher,
    stopStatus: result.stopStatus,
    stoppedPidCount: result.stoppedPidCount,
    stopError: result.stopError.slice(0, 500)
  };
}
