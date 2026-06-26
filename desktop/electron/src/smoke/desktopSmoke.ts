import { join } from "node:path";

export type DesktopSmokeSummaryInput = {
  workspaceRoot: string;
  configPath: string;
  launcherUrl: string;
  workbenchUrl: string;
  controlToken: string;
  packaged: boolean;
};

export function desktopSmokeSummary(input: DesktopSmokeSummaryInput) {
  return {
    schemaVersion: 1,
    mode: "electron_package_smoke",
    workspaceRoot: input.workspaceRoot,
    operatorConfigPath: input.configPath,
    packaged: input.packaged,
    launcherOrigin: input.launcherUrl ? new URL(input.launcherUrl).origin : "",
    workbenchOrigin: input.workbenchUrl ? new URL(input.workbenchUrl).origin : "",
    controlTokenPresent: Boolean(input.controlToken)
  };
}

export function desktopSmokeSummaryPath(workspaceRoot: string): string {
  return join(workspaceRoot, ".runtime", "launcher", "electron-smoke-summary.json");
}
