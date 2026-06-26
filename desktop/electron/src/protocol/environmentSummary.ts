export type LauncherEnvironmentSummary = {
  schemaVersion: 1;
  paths: {
    desktopBundleRoot: string;
    resourcesRoot: string;
    workspaceRoot: string;
    userDataRoot: string;
  };
  pythonSource: "launcher_resolver" | "env_override";
  pythonPath: string;
  operatorConfigPath: string;
  launcherUrl: string;
  workbenchUrl: string;
  controlTokenPresent: boolean;
  workspaceId: string;
  launcherInstanceId: string;
  protocolVersion: number;
  minDesktopProtocolVersion: number;
  maxDesktopProtocolVersion: number;
  capabilities: string[];
  nodeEnv: "development" | "production" | "test";
};

export function createLauncherEnvironmentSummary(input: LauncherEnvironmentSummary): LauncherEnvironmentSummary {
  return { ...input, schemaVersion: 1 };
}

export function redactEnvironmentSummary(summary: LauncherEnvironmentSummary): LauncherEnvironmentSummary {
  return { ...summary, controlTokenPresent: summary.controlTokenPresent };
}
