import { join } from "node:path";

export type DesktopSmokeSummaryInput = {
  workspaceRoot: string;
  configPath: string;
  launcherUrl: string;
  workbenchUrl: string;
  controlToken: string;
  packaged: boolean;
  bootstrap?: DesktopSmokeBootstrapSummary;
  shutdown?: DesktopSmokeShutdownSummary;
};

export type DesktopSmokeBootstrapSummary = {
  attempted: boolean;
  parsed: boolean;
  mode: string;
  launcherBackendPid: number;
  protocolVersion: number;
  capabilities: string[];
  launcherOrigin: string;
  workbenchOrigin: string;
  errorType: string;
  errorMessage: string;
};

export type DesktopSmokeShutdownSummary = {
  attempted: boolean;
  stopPythonLauncher: boolean;
  stopStatus: "stopped" | "skipped" | "failed" | "not_requested";
  stoppedPidCount: number;
  stopError: string;
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
    controlTokenPresent: Boolean(input.controlToken),
    bootstrap: input.bootstrap ?? emptyDesktopSmokeBootstrapSummary(),
    shutdown: input.shutdown ?? emptyDesktopSmokeShutdownSummary()
  };
}

export function desktopSmokeSummaryPath(workspaceRoot: string): string {
  return join(workspaceRoot, ".runtime", "launcher", "electron-smoke-summary.json");
}

export function emptyDesktopSmokeBootstrapSummary(): DesktopSmokeBootstrapSummary {
  return {
    attempted: false,
    parsed: false,
    mode: "",
    launcherBackendPid: 0,
    protocolVersion: 0,
    capabilities: [],
    launcherOrigin: "",
    workbenchOrigin: "",
    errorType: "",
    errorMessage: ""
  };
}

export function emptyDesktopSmokeShutdownSummary(): DesktopSmokeShutdownSummary {
  return {
    attempted: false,
    stopPythonLauncher: false,
    stopStatus: "not_requested",
    stoppedPidCount: 0,
    stopError: ""
  };
}
