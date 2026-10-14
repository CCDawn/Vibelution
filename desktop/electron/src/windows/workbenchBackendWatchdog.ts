/**
 * Shell-side liveness watchdog for ALREADY-OPEN workbench windows.
 *
 * Incident background (2026-10): an external launcher sweep killed every
 * workbench backend (ports 8000/8002) while the Electron shell and its
 * workbench windows stayed open. Existing checks only run at window-open
 * (workbenchOpenBackendGate), at instance-start supervision, or inside restart
 * chains — nothing observed already-open windows, so users stared at frozen
 * pages with zero shell-level indication until a manual full restart brought a
 * backend back that nothing reloaded the old windows onto.
 *
 * This module is deliberately conservative: it only OBSERVES and RELOADS
 * windows. It never spawns or kills backend processes, never talks to restart
 * intents or the lifecycle coordinator, and never creates a visible console.
 * Recovery is delegated to whatever owner already restarted the backend; the
 * watchdog just notices "origin answers /api/health again" and reloads the
 * affected windows once.
 */

export const WORKBENCH_BACKEND_WATCHDOG_INTERVAL_MS = 8000;
export const WORKBENCH_BACKEND_WATCHDOG_PROBE_TIMEOUT_MS = 2500;
export const WORKBENCH_BACKEND_WATCHDOG_DEGRADE_THRESHOLD = 3;
export const WORKBENCH_BACKEND_OFFLINE_TITLE_SUFFIX = " · 后端离线";

const LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost"]);

export type BackendProbeResult = "healthy" | "dead";

export type WorkbenchBackendWatchdogState = "healthy" | "degraded";

export type WorkbenchBackendWatchdogAction =
  | { kind: "degraded"; origin: string }
  | { kind: "reload-windows"; origin: string };

export type WorkbenchBackendWatchdogLogEvent =
  | { kind: "tick-error"; message: string }
  | { kind: "origin-degraded"; origin: string }
  | { kind: "origin-recovered"; origin: string };

type OriginTracker = {
  state: WorkbenchBackendWatchdogState;
  consecutiveDead: number;
};

/**
 * Pure decision core: a per-origin state machine fed with probe outcomes.
 *
 * Why a threshold: a single dropped probe (route warm-up, GC pause, transient
 * connection reset) must not mark a live backend offline and churn window
 * titles. Why silence while degraded: repeated "degraded" emissions would
 * re-suffix titles every tick; the transition is the only event the wiring
 * needs. A degraded origin that becomes healthy again emits exactly one
 * reload-windows action and returns to the healthy baseline (so the next
 * outage must re-cross the threshold).
 */
export class WorkbenchBackendWatchdogCore {
  private readonly origins = new Map<string, OriginTracker>();

  record(origin: string, result: BackendProbeResult): WorkbenchBackendWatchdogAction[] {
    const tracker = this.origins.get(origin) ?? { state: "healthy", consecutiveDead: 0 };
    if (result === "healthy") {
      this.origins.set(origin, { state: "healthy", consecutiveDead: 0 });
      return tracker.state === "degraded" ? [{ kind: "reload-windows", origin }] : [];
    }
    const consecutiveDead = tracker.consecutiveDead + 1;
    if (tracker.state === "degraded") {
      this.origins.set(origin, { state: "degraded", consecutiveDead });
      return [];
    }
    if (consecutiveDead >= WORKBENCH_BACKEND_WATCHDOG_DEGRADE_THRESHOLD) {
      this.origins.set(origin, { state: "degraded", consecutiveDead });
      return [{ kind: "degraded", origin }];
    }
    this.origins.set(origin, { state: "healthy", consecutiveDead });
    return [];
  }

  stateOf(origin: string): WorkbenchBackendWatchdogState {
    return this.origins.get(origin)?.state ?? "healthy";
  }

  reset(): void {
    this.origins.clear();
  }
}

/**
 * Minimal structural view of a window the watchdog needs. Kept free of
 * Electron types so the module (and its tests) never imports Electron; the
 * main-process adapter maps BrowserWindow onto this shape.
 */
export type WatchdogWindowHandle = {
  id: number;
  getUrl(): string;
  isDestroyed(): boolean;
  reload(): void;
  getTitle(): string;
  setTitle(title: string): void;
};

export type WorkbenchBackendWatchdogDeps = {
  intervalMs?: number;
  probeTimeoutMs?: number;
  /** Enumerate candidate windows; production maps BrowserWindow.getAllWindows(). */
  listWindows: () => WatchdogWindowHandle[];
  /** Defaults to GET {origin}/api/health with status < 500 = healthy. */
  probe?: (origin: string) => Promise<BackendProbeResult>;
  /** Notified once per recovered origin (telemetry hook; windows reload regardless). */
  onReload?: (origin: string) => void;
  log?: (event: WorkbenchBackendWatchdogLogEvent) => void;
  scheduler?: WorkbenchBackendWatchdogScheduler;
};

export type WorkbenchBackendWatchdogScheduler = {
  setInterval: (handler: () => void, ms: number) => unknown;
  clearInterval: (handle: unknown) => void;
};

export type WorkbenchBackendWatchdogHandle = {
  /** Stop the periodic tick and drop all per-origin state. Idempotent. */
  dispose(): void;
  /** Drop decision state (e.g. after an external reload) without stopping. */
  reset(): void;
};

/**
 * Classify a window URL into the loopback HTTP(S) origin the watchdog should
 * probe. Empty string means "not this watchdog's business": launcher windows
 * (vibelution-launcher://), error/data pages a failed navigation can leave
 * behind, file URLs, and any non-loopback host are all skipped so the probe
 * list stays exactly "workbench backends this shell serves".
 */
export function workbenchOriginForWindowUrl(rawUrl: string): string {
  let url: URL;
  try {
    url = new URL(rawUrl);
  } catch {
    return "";
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    return "";
  }
  if (!LOOPBACK_HOSTS.has(url.hostname)) {
    return "";
  }
  return url.origin;
}

/**
 * Mirror how workbenchBackendHealth/servingVersion treat /api/health, but
 * looser on purpose: this is a liveness signal for reload decisions, not a
 * readiness gate, so any response below 500 (including 503 "starting" from a
 * backend that just came back) counts as healthy. A backend answering HTTP at
 * all is the observable the frozen windows were missing.
 */
export function defaultWorkbenchOriginHealthProbe(timeoutMs: number): (origin: string) => Promise<BackendProbeResult> {
  const timeout = Math.max(1, timeoutMs);
  return async (origin) => {
    try {
      const response = await fetch(`${origin}/api/health`, {
        method: "GET",
        redirect: "manual",
        signal: AbortSignal.timeout(timeout)
      });
      return response.status < 500 ? "healthy" : "dead";
    } catch {
      return "dead";
    }
  };
}

/**
 * Start the watchdog. Each tick enumerates live windows, derives the distinct
 * loopback HTTP(S) origins, probes each once, feeds the core, and applies the
 * emitted actions: on degrade, matching window titles gain an offline suffix
 * (original title captured at degrade time); on recovery, the suffix is
 * stripped and every matching window is reloaded exactly once so an
 * externally-restarted backend is actually picked up by the old shell's
 * windows.
 */
export function startWorkbenchBackendWatchdog(deps: WorkbenchBackendWatchdogDeps): WorkbenchBackendWatchdogHandle {
  const intervalMs = Math.max(1, deps.intervalMs ?? WORKBENCH_BACKEND_WATCHDOG_INTERVAL_MS);
  const scheduler = deps.scheduler ?? {
    setInterval: (handler: () => void, ms: number) => setInterval(handler, ms),
    clearInterval: (handle: unknown) => clearInterval(handle as ReturnType<typeof setInterval>)
  };
  const log = deps.log ?? (() => undefined);
  const probe = deps.probe ?? defaultWorkbenchOriginHealthProbe(deps.probeTimeoutMs ?? WORKBENCH_BACKEND_WATCHDOG_PROBE_TIMEOUT_MS);
  const core = new WorkbenchBackendWatchdogCore();
  /** Window id -> title captured when the suffix was applied, keyed per degrade. */
  const suffixedTitles = new Map<number, { origin: string; title: string }>();
  let timer: unknown = null;
  let disposed = false;
  let tickRunning = false;

  const windowsForOrigin = (windows: WatchdogWindowHandle[], origin: string): WatchdogWindowHandle[] =>
    windows.filter((window) => {
      try {
        return workbenchOriginForWindowUrl(window.getUrl()) === origin;
      } catch {
        return false;
      }
    });

  const applySuffix = (windows: WatchdogWindowHandle[], origin: string): void => {
    for (const window of windowsForOrigin(windows, origin)) {
      if (window.isDestroyed()) {
        continue;
      }
      let title = "";
      try {
        title = window.getTitle();
      } catch {
        continue;
      }
      if (title.endsWith(WORKBENCH_BACKEND_OFFLINE_TITLE_SUFFIX)) {
        continue;
      }
      if (!suffixedTitles.has(window.id)) {
        suffixedTitles.set(window.id, { origin, title });
      }
      window.setTitle(`${title}${WORKBENCH_BACKEND_OFFLINE_TITLE_SUFFIX}`);
    }
  };

  const applyRecovery = (windows: WatchdogWindowHandle[], origin: string): void => {
    for (const window of windowsForOrigin(windows, origin)) {
      const captured = suffixedTitles.get(window.id);
      if (captured !== undefined && captured.origin === origin) {
        suffixedTitles.delete(window.id);
      }
      if (window.isDestroyed()) {
        continue;
      }
      let title = "";
      try {
        title = window.getTitle();
      } catch {
        continue;
      }
      if (captured !== undefined && title === `${captured.title}${WORKBENCH_BACKEND_OFFLINE_TITLE_SUFFIX}`) {
        window.setTitle(captured.title);
      } else if (title.endsWith(WORKBENCH_BACKEND_OFFLINE_TITLE_SUFFIX)) {
        window.setTitle(title.slice(0, -WORKBENCH_BACKEND_OFFLINE_TITLE_SUFFIX.length));
      }
      // Guarded reload: the window may close between enumeration and here.
      window.reload();
    }
    deps.onReload?.(origin);
  };

  const tick = async (): Promise<void> => {
    if (tickRunning) {
      return;
    }
    tickRunning = true;
    try {
      const windows = deps.listWindows().filter((window) => {
        try {
          return !window.isDestroyed() && workbenchOriginForWindowUrl(window.getUrl()) !== "";
        } catch {
          return false;
        }
      });
      const origins = Array.from(
        new Set(windows.map((window) => workbenchOriginForWindowUrl(window.getUrl())))
      );
      if (origins.length === 0) {
        return;
      }
      const outcomes = await Promise.all(
        origins.map(async (origin) => ({ origin, result: await probe(origin) }))
      );
      for (const outcome of outcomes) {
        for (const action of core.record(outcome.origin, outcome.result)) {
          if (action.kind === "degraded") {
            log({ kind: "origin-degraded", origin: action.origin });
            applySuffix(windows, action.origin);
          } else {
            log({ kind: "origin-recovered", origin: action.origin });
            applyRecovery(windows, action.origin);
          }
        }
      }
    } catch (error: unknown) {
      log({ kind: "tick-error", message: error instanceof Error ? error.message : String(error) });
    } finally {
      tickRunning = false;
    }
  };

  timer = scheduler.setInterval(() => void tick(), intervalMs);

  return {
    dispose(): void {
      if (disposed) {
        return;
      }
      disposed = true;
      if (timer !== null) {
        scheduler.clearInterval(timer);
        timer = null;
      }
      suffixedTitles.clear();
      core.reset();
    },
    reset(): void {
      suffixedTitles.clear();
      core.reset();
    }
  };
}
