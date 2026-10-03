import { mainLineBackendIsReachable, sameProjectRoot } from "../process/workbenchBackend.js";
import {
  defaultFetchWorkbenchHealth,
  waitForBackendHealthy,
  workbenchHealthPayloadReady,
  workbenchHealthUrl,
  type WorkbenchHealthResponse
} from "../process/workbenchBackendHealth.js";

/**
 * Gate in front of every Workbench open action: make sure the Workbench
 * backend is actually serving before the shell creates a window and calls
 * loadURL. A stale resolution (ports.json / state.json can still name port
 * 8000 after the backend died) must not be mistaken for a live backend, so
 * the default reachability check is the existing main-line observation —
 * the same mechanism the lifecycle orchestrator already trusts.
 *
 * When the backend is down, the caller-provided startLifecycle (the existing
 * orchestrateLauncherLifecycle("start") path in main.ts) brings it back
 * before the open proceeds. The wait afterwards is bounded: if the backend
 * does not settle within the budget the gate throws and the caller falls
 * through to the visible bilingual error status instead of blocking the UI
 * forever.
 *
 * A live PID or TCP listener is only a reachability hint. Reuse also requires
 * a ready health response from this workspace; release and process identity
 * validation remain at the lifecycle startup boundary.
 */

export const WORKBENCH_OPEN_START_WAIT_TIMEOUT_MS = 30_000;

export type WorkbenchOpenBackendGateInput = {
  workspaceRoot: string;
  workbenchUrl: string;
  /** Defaults to the existing main-line backend observation. */
  isBackendReachable?: (workspaceRoot: string) => Promise<boolean>;
  isBackendHealthy?: (workspaceRoot: string, url: string) => Promise<boolean>;
  /**
   * The existing backend startup path (main.ts wires
   * orchestrateLauncherLifecycle("start")). Omitted only in unit tests; a
   * production caller must always supply it so a dead backend is restarted
   * through the lifecycle owner.
   */
  startLifecycle?: () => Promise<unknown>;
  /** Bounded readiness wait; defaults to the workspace-bound health poll. */
  waitForHealthy?: (input: { url: string; timeoutMs: number }) => Promise<void>;
  /**
   * Budget for the recovery attempt: the lifecycle start must settle and the
   * backend must become healthy within this many milliseconds. A slower start
   * (e.g. a frontend rebuild) is not cancelled — it keeps running in the
   * background and its own post-start window orchestration still opens the
   * workbench — but the open action fails now instead of pinning the desktop
   * action loop.
   */
  startWaitTimeoutMs?: number;
};

export type WorkbenchOpenBackendGateResult = {
  /** True when the gate had to run the lifecycle start path. */
  started: boolean;
};

export async function ensureWorkbenchBackendReady(
  input: WorkbenchOpenBackendGateInput
): Promise<WorkbenchOpenBackendGateResult> {
  const isBackendReachable = input.isBackendReachable ?? ((root: string) => mainLineBackendIsReachable(root));
  const target = new URL(input.workbenchUrl);
  const host = target.hostname;
  const port = Number(target.port || (target.protocol === "https:" ? 443 : 80));
  const fetchHealth = workspaceHealthFetch(input.workspaceRoot);
  const isBackendHealthy = input.isBackendHealthy ?? (async () => {
    try {
      const response = await fetchHealth(workbenchHealthUrl(port, host));
      return response.status === 200;
    } catch {
      return false;
    }
  });
  if (await isBackendReachable(input.workspaceRoot)
    && await isBackendHealthy(input.workspaceRoot, input.workbenchUrl)) {
    return { started: false };
  }
  const budgetMs = input.startWaitTimeoutMs ?? WORKBENCH_OPEN_START_WAIT_TIMEOUT_MS;
  const expiresAt = Date.now() + budgetMs;
  if (input.startLifecycle) {
    await settleWithinBudget(input.startLifecycle, budgetMs);
  }
  const waitForHealthy = input.waitForHealthy
    ?? ((wait: { url: string; timeoutMs: number }) => waitForBackendHealthy({
      port,
      host,
      fetchHealth,
      timeoutMs: wait.timeoutMs
    }));
  const remainingMs = Math.max(0, expiresAt - Date.now());
  if (remainingMs <= 0) {
    throw new Error(`workbench backend readiness exceeded ${budgetMs}ms`);
  }
  await waitForHealthy({ url: input.workbenchUrl, timeoutMs: remainingMs });
  return { started: true };
}

function workspaceHealthFetch(workspaceRoot: string): (url: string) => Promise<WorkbenchHealthResponse> {
  const fetchHealth = defaultFetchWorkbenchHealth({ httpTimeoutMs: 1500 });
  return async (url) => {
    const response = await fetchHealth(url);
    if (response.status !== 200 || !response.json) {
      return { status: 503 };
    }
    const payload = await response.json();
    if (!workbenchHealthPayloadReady(payload)
      || !sameProjectRoot(String((payload as Record<string, unknown>).workspaceRoot || ""), workspaceRoot)) {
      return { status: 503 };
    }
    return { status: 200, json: async () => payload };
  };
}

/**
 * Bound one lifecycle attempt. The attempt itself never cancels: a slow or
 * still-running start keeps going in the background, but this open action
 * fails within the budget so the caller can fall through to the visible
 * error status instead of blocking the desktop action loop indefinitely.
 */
async function settleWithinBudget(start: () => Promise<unknown>, budgetMs: number): Promise<void> {
  const failures: unknown[] = [];
  const attempt: Promise<"settled" | "failed"> = Promise.resolve()
    .then(start)
    .then(
      () => "settled" as const,
      (error: unknown) => {
        failures.push(error);
        return "failed" as const;
      }
    );
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout: Promise<"timeout"> = new Promise<void>((resolve) => {
    timer = setTimeout(resolve, Math.max(0, budgetMs));
  }).then(() => "timeout" as const);
  let outcome: "settled" | "failed" | "timeout";
  try {
    outcome = await Promise.race([attempt, timeout]);
  } finally {
    clearTimeout(timer);
  }
  if (outcome === "timeout") {
    throw new Error(
      `workbench backend start did not settle within ${budgetMs}ms; it keeps running in the background`
    );
  }
  if (failures.length > 0) {
    throw failures[0];
  }
}
