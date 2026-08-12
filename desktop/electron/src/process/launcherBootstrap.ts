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

const STARTUP_TELEMETRY_DRAIN_TIMEOUT_MS = 250;
const MAX_STARTUP_TELEMETRY_DRAIN_TIMEOUT_MS = 1000;

/**
 * Give terminal startup telemetry one bounded opportunity to flush. A stalled
 * control-plane request must never prevent Electron from reaching app.quit().
 */
export function drainTelemetryWithDeadline(
  recordTelemetry: () => Promise<void>,
  timeoutMs = STARTUP_TELEMETRY_DRAIN_TIMEOUT_MS
): Promise<void> {
  const requestedTimeoutMs = Number.isFinite(timeoutMs)
    ? Math.round(timeoutMs)
    : STARTUP_TELEMETRY_DRAIN_TIMEOUT_MS;
  const boundedTimeoutMs = Math.max(1, Math.min(requestedTimeoutMs, MAX_STARTUP_TELEMETRY_DRAIN_TIMEOUT_MS));

  return new Promise<void>((resolve) => {
    let completed = false;
    const finish = () => {
      if (completed) {
        return;
      }
      completed = true;
      clearTimeout(timer);
      resolve();
    };
    const timer = setTimeout(finish, boundedTimeoutMs);
    try {
      void recordTelemetry().then(finish, finish);
    } catch {
      finish();
    }
  });
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
