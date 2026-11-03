import { waitForWorkbenchHttp } from "./workbenchHttpReady.js";

/**
 * Bounded auto-recovery behind the Workbench waiting status page.
 *
 * Background: when the open-time backend gate (workbenchOpenBackendGate) or
 * the navigation itself fails, the window shows a local data: status page.
 * The already-open-window watchdog (workbenchBackendWatchdog) deliberately
 * skips data: URLs, so such a window never reloaded on its own — the user had
 * to notice and reopen by hand even though the backend typically came back a
 * few seconds later (the gate's 30s budget is shorter than a cold start with
 * a frontend rebuild).
 *
 * This runner is the smallest fix: poll the real workbench URL with the
 * existing waitForWorkbenchHttp (one bounded wait, one reload), and let the
 * owner swap to the terminal error page when the budget runs out. It owns no
 * window state; the provider supplies three closures and keeps the single
 * live run per workbench window.
 *
 * Reload discipline: waitForWorkbenchHttp resolves exactly once, so a run
 * reloads at most once; it never reloads per tick. Re-entrancy is the
 * caller's job (a new run supersedes the previous via `isStillWaiting` and
 * the abort signal), and a reload that itself fails must not spawn another
 * waiting run — the provider shows the terminal page for a nested failure.
 */

/** 60–120s band: longer than the gate's 30s so a slow cold start still lands. */
export const WORKBENCH_WAITING_RECOVERY_TIMEOUT_MS = 90_000;
/** 2–4s band: fast enough to feel automatic, slow enough not to hammer a starting backend. */
export const WORKBENCH_WAITING_RECOVERY_POLL_INTERVAL_MS = 3_000;

export type WorkbenchHttpWait = (input: {
  url: string;
  timeoutMs: number;
  pollIntervalMs?: number;
  signal?: AbortSignal;
}) => Promise<void>;

export type WorkbenchWaitingRecoveryOutcome =
  /** The backend answered and the real origin was reloaded. */
  | "recovered"
  /** The budget ran out; the terminal error page was shown. */
  | "timed-out"
  /** The window moved on (user retry, close, newer run); nothing was touched. */
  | "superseded"
  /** The backend answered but the reload threw; the terminal error page was shown. */
  | "failed";

export type WorkbenchWaitingRecoveryResult = {
  outcome: WorkbenchWaitingRecoveryOutcome;
  targetUrl: string;
  error?: string;
};

export type WorkbenchWaitingRecoveryInput = {
  /** The real workbench URL to poll and then reload. */
  targetUrl: string;
  timeoutMs?: number;
  pollIntervalMs?: number;
  /** Aborting ends the poll early with "superseded"; the owner uses it on close / newer run. */
  signal?: AbortSignal;
  /** Defaults to waitForWorkbenchHttp; tests inject a fake. */
  waitForHttp?: WorkbenchHttpWait;
  /** Whether the window still shows the waiting page this run is responsible for. */
  isStillWaiting: () => boolean;
  /** Reload the real origin (the provider's openOrFocusWorkbench). */
  recover: () => Promise<unknown>;
  /** Swap the window to the terminal error page. Best-effort; errors are swallowed. */
  showFinalError: () => Promise<unknown> | unknown;
};

export async function runWorkbenchWaitingRecovery(
  input: WorkbenchWaitingRecoveryInput
): Promise<WorkbenchWaitingRecoveryResult> {
  const targetUrl = input.targetUrl;
  const superseded = (): boolean => input.signal?.aborted === true || !input.isStillWaiting();
  if (superseded()) {
    return { outcome: "superseded", targetUrl };
  }
  const waitForHttp = input.waitForHttp ?? waitForWorkbenchHttp;
  const timeoutMs = Math.max(0, input.timeoutMs ?? WORKBENCH_WAITING_RECOVERY_TIMEOUT_MS);
  const pollIntervalMs = Math.max(0, input.pollIntervalMs ?? WORKBENCH_WAITING_RECOVERY_POLL_INTERVAL_MS);

  try {
    await waitForHttp({ url: targetUrl, timeoutMs, pollIntervalMs, signal: input.signal });
  } catch (error: unknown) {
    if (superseded()) {
      return { outcome: "superseded", targetUrl };
    }
    await showFinalErrorQuietly(input);
    return { outcome: "timed-out", targetUrl, error: describe(error) };
  }

  if (superseded()) {
    return { outcome: "superseded", targetUrl };
  }
  try {
    await input.recover();
    return { outcome: "recovered", targetUrl };
  } catch (error: unknown) {
    // Abort is the only clean supersede here. A reload failure often ends
    // with the terminal page already on screen (the provider loads it in the
    // nested failure path); the page-URL check would then misread that as
    // "moved on" and hide a real failure from the telemetry hook.
    if (input.signal?.aborted) {
      return { outcome: "superseded", targetUrl, error: describe(error) };
    }
    await showFinalErrorQuietly(input);
    return { outcome: "failed", targetUrl, error: describe(error) };
  }
}

async function showFinalErrorQuietly(input: WorkbenchWaitingRecoveryInput): Promise<void> {
  try {
    await input.showFinalError();
  } catch {
    // The terminal page is best-effort; the outcome already carries the cause.
  }
}

function describe(error: unknown): string {
  return (error instanceof Error ? error.message : String(error)).slice(0, 300);
}
