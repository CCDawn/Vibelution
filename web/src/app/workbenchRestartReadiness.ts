export type WorkbenchHealthSnapshot = {
  status?: string;
  pid?: number;
  routesReady?: boolean;
  shellReady?: boolean;
};

export function isRestartedBackendReady(
  previousPid: number,
  health: WorkbenchHealthSnapshot | null | undefined,
): health is WorkbenchHealthSnapshot & { status: "ok"; pid: number } {
  if (!health) return false;
  const pid = Number(health.pid);
  if (health.status !== "ok" || !Number.isFinite(pid) || pid <= 0) return false;
  if (health.routesReady === false || health.shellReady === false) return false;
  // A recovery restart may begin with no serving backend at all, so there is
  // no previous PID to differ from. Any ready backend is then the new one.
  return previousPid <= 0 || pid !== previousPid;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Wait for the replacement backend, not the old one.
 *
 * Restart admission returns before the old backend has finished saving active
 * work. Reloading at that point lands the document on a closing server and the
 * user sees a connection failure during an otherwise normal update. Polling
 * the public health endpoint from the current document keeps the restart
 * overlay in place until a different, ready PID is actually serving.
 */
export async function waitForRestartedBackend(input: {
  previousPid: number;
  timeoutMs?: number;
  intervalMs?: number;
  fetchImpl?: typeof fetch;
  shouldContinue?: () => boolean;
}): Promise<{ pid: number }> {
  const timeoutMs = Math.max(1, input.timeoutMs ?? 120_000);
  const intervalMs = Math.max(1, input.intervalMs ?? 1_000);
  const fetchImpl = input.fetchImpl ?? fetch;
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    if (input.shouldContinue && !input.shouldContinue()) {
      throw new Error("RESTART_WAIT_CANCELLED");
    }
    try {
      // A half-open connection must not pin the restart overlay past its own
      // timeout; each poll gets only the time left in the wait budget.
      const remainingMs = Math.max(1, timeoutMs - (Date.now() - startedAt));
      const signal = typeof AbortSignal !== "undefined" && typeof AbortSignal.timeout === "function"
        ? AbortSignal.timeout(Math.min(5_000, remainingMs))
        : undefined;
      const response = await fetchImpl("/api/health", {
        cache: "no-store",
        ...(signal ? { signal } : {}),
      });
      if (response.ok) {
        const health = await response.json() as WorkbenchHealthSnapshot;
        if (isRestartedBackendReady(input.previousPid, health)) {
          return { pid: Number(health.pid) };
        }
      }
    } catch {
      // The old server is expected to disappear; the next poll is the signal.
    }
    if (input.shouldContinue && !input.shouldContinue()) {
      throw new Error("RESTART_WAIT_CANCELLED");
    }
    await sleep(intervalMs);
  }
  throw new Error("RESTART_READY_TIMEOUT");
}
