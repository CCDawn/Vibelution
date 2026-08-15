import type { LauncherStatusSummary } from "../protocol/launcherControlClient.js";

class WorkbenchLifecycleCommandFailed extends Error {}

export async function waitForWorkbenchLifecycleReady(input: {
  commandId: string;
  readStatus: () => Promise<LauncherStatusSummary>;
  timeoutMs: number;
  pollIntervalMs?: number;
}): Promise<LauncherStatusSummary> {
  const commandId = input.commandId.trim();
  if (!commandId) {
    throw new Error("workbench lifecycle command id is required before opening the window");
  }
  const startedAt = Date.now();
  const pollIntervalMs = Math.max(0, input.pollIntervalMs ?? 500);
  let lastReadError = "";
  do {
    try {
      const status = await input.readStatus();
      const result = status.lifecycleResults.find((item) => item.commandId === commandId && item.completed);
      if (result) {
        if (!result.ok) {
          throw new WorkbenchLifecycleCommandFailed(
            result.message || `workbench lifecycle command failed: ${commandId}`
          );
        }
        if (workbenchBackendReady(status)) {
          return status;
        }
      }
      lastReadError = "";
    } catch (error: unknown) {
      const detail = error instanceof Error ? error.message : String(error);
      if (error instanceof WorkbenchLifecycleCommandFailed) {
        throw error;
      }
      lastReadError = detail;
    }
    if (Date.now() - startedAt >= input.timeoutMs) {
      break;
    }
    if (pollIntervalMs > 0) {
      await new Promise((resolve) => setTimeout(resolve, pollIntervalMs));
    }
  } while (Date.now() - startedAt < input.timeoutMs);
  const suffix = lastReadError ? `; last status error: ${lastReadError}` : "";
  throw new Error(`workbench lifecycle readiness timed out for ${commandId}${suffix}`);
}

function workbenchBackendReady(status: LauncherStatusSummary): boolean {
  const observedState = status.observedState.trim().toLowerCase();
  const consistency = status.lifecycleConsistency.trim().toLowerCase();
  return (
    status.backendHealthy
    && status.backendPortListening
    && (observedState === "open" || observedState === "partial")
    && (consistency === "consistent" || consistency === "browser_missing")
  );
}
