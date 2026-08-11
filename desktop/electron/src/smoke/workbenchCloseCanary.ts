import { join } from "node:path";

export type DesktopWorkbenchCloseCanarySummaryInput = {
  workspaceRoot: string;
  configPath: string;
  closeId: string;
  desktopSessionId: string;
  desktopSessionRevision: number;
  controlToken: string;
};

/**
 * Secret-free acknowledgement written only after the native window-close path
 * has completed the Launcher transaction.
 */
export function desktopWorkbenchCloseCanarySummary(input: DesktopWorkbenchCloseCanarySummaryInput) {
  return {
    schemaVersion: 1,
    mode: "electron_workbench_close_canary",
    phase: "succeeded",
    workspaceRoot: input.workspaceRoot,
    operatorConfigPath: input.configPath,
    closeId: input.closeId,
    desktopSessionId: input.desktopSessionId,
    desktopSessionRevision: input.desktopSessionRevision,
    controlTokenPresent: Boolean(input.controlToken)
  };
}

export function desktopWorkbenchCloseCanarySummaryPath(workspaceRoot: string): string {
  return join(workspaceRoot, ".runtime", "launcher", "electron-workbench-close-canary-summary.json");
}
