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

/**
 * Start best-effort startup telemetry without making it part of the bootstrap
 * result contract. Telemetry failures must never reject or delay startup.
 */
export function scheduleTelemetryWithoutWaiting(recordTelemetry: () => Promise<void>): void {
  setImmediate(() => {
    try {
      void recordTelemetry().catch(() => undefined);
    } catch {
      // A synchronous telemetry failure is still observational only.
    }
  });
}

export function completeBootstrapWithoutWaitingForTelemetry<T>(
  result: T,
  recordTelemetry: () => Promise<void>
): T {
  scheduleTelemetryWithoutWaiting(recordTelemetry);
  return result;
}

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
