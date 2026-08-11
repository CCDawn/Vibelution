export type LauncherBootstrapMode = "attached" | "started";

export type LauncherBootstrapResult = {
  schemaVersion: 1;
  workspaceRoot: string;
  operatorConfigPath: string;
  workspaceId: string;
  launcherInstanceId: string;
  mode: LauncherBootstrapMode;
  launcherBackendPid: number;
  launcherUrl: string;
  workbenchUrl: string;
  ready: boolean;
  protocolVersion: number;
  minDesktopProtocolVersion: number;
  maxDesktopProtocolVersion: number;
  capabilities: string[];
};

const REQUIRED_LAUNCHER_CAPABILITIES = [
  "desktop_actions.claim",
  "workbench_close.transaction.v1"
] as const;

export function parseLauncherBootstrap(raw: string): LauncherBootstrapResult {
  const parsed = JSON.parse(raw) as LauncherBootstrapResult;
  if (parsed.schemaVersion !== 1 || !parsed.ready || !parsed.launcherUrl || !parsed.workspaceRoot) {
    throw new Error("invalid launcher bootstrap result");
  }
  if (!parsed.capabilities.includes(REQUIRED_LAUNCHER_CAPABILITIES[0])) {
    throw new Error("launcher bootstrap is missing desktop action capability");
  }
  if (!parsed.capabilities.includes(REQUIRED_LAUNCHER_CAPABILITIES[1])) {
    throw new Error("launcher bootstrap is missing transactional Workbench-close capability");
  }
  return parsed;
}
