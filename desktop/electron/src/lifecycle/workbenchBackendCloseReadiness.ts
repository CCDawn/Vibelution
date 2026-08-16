import type { LauncherStatusSummary } from "../protocol/launcherControlClient.js";

/** True when Runtime Manager has finished stopping the backend and Electron may close the window. */
export function isWorkbenchBackendSettledForWindowClose(status: LauncherStatusSummary): boolean {
  const observedState = status.observedState.trim().toLowerCase();
  const consistency = status.lifecycleConsistency.trim().toLowerCase();
  const phase = status.phase.trim().toLowerCase();

  if (observedState === "closed") {
    return true;
  }

  // Electron two-phase close: backend is down but observedState stays partial until the window closes.
  if (consistency === "external_window_owner_pending_ack") {
    return true;
  }

  if (!status.backendHealthy && !status.backendPortListening && phase === "closing") {
    return observedState === "partial" || observedState === "open";
  }

  return false;
}

export async function waitForWorkbenchBackendSettledForWindowClose(input: {
  readStatus: () => Promise<LauncherStatusSummary>;
  timeoutMs: number;
  pollIntervalMs?: number;
}): Promise<boolean> {
  const startedAt = Date.now();
  const pollIntervalMs = Math.max(0, input.pollIntervalMs ?? 1000);
  do {
    try {
      const status = await input.readStatus();
      if (isWorkbenchBackendSettledForWindowClose(status)) {
        return true;
      }
    } catch {
      // Treat control-plane read failures as not-yet-closed; the next poll retries.
    }
    if (Date.now() - startedAt >= input.timeoutMs) {
      break;
    }
    if (pollIntervalMs > 0) {
      await new Promise((resolve) => setTimeout(resolve, pollIntervalMs));
    }
  } while (Date.now() - startedAt < input.timeoutMs);
  return false;
}
