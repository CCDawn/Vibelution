import { useEffect, useState } from "react";

export type PollingInterval = number | false;
export const STARTUP_BACKGROUND_WARMUP_MS = 45_000;
export const SHELL_DEFERRED_POLL_BOOT_DELAY_MS = 6_000;

export function isDocumentVisible(visibilityState?: string): boolean {
  return visibilityState === undefined || visibilityState === "visible";
}

export function currentDocumentVisible(): boolean {
  if (typeof document === "undefined") {
    return true;
  }
  return isDocumentVisible(document.visibilityState);
}

export function resolvePollingInterval(
  pageVisible: boolean,
  foregroundMs: PollingInterval,
  options: {
    backgroundMs?: PollingInterval;
    force?: boolean;
  } = {},
): PollingInterval {
  if (options.force || pageVisible) {
    return foregroundMs;
  }
  return options.backgroundMs ?? false;
}

export function resolveLauncherStatusPollingInterval(
  pageVisible: boolean,
  options: {
    lifecycleChanging: boolean;
    commandActive: boolean;
  },
): PollingInterval {
  if (options.lifecycleChanging || options.commandActive) {
    return resolvePollingInterval(pageVisible, 4_000, { backgroundMs: 15_000 });
  }
  return resolvePollingInterval(pageVisible, 15_000, { backgroundMs: 60_000 });
}

export function isStartupWarmupActive(ready: boolean, elapsedMs: number, warmupMs = STARTUP_BACKGROUND_WARMUP_MS): boolean {
  if (ready) {
    return false;
  }
  return warmupMs <= 0 || elapsedMs < warmupMs;
}

export function usePageVisibility(): boolean {
  const [pageVisible, setPageVisible] = useState(currentDocumentVisible);

  useEffect(() => {
    if (typeof document === "undefined") {
      return;
    }

    const update = () => setPageVisible(currentDocumentVisible());
    document.addEventListener("visibilitychange", update);
    return () => {
      document.removeEventListener("visibilitychange", update);
    };
  }, []);

  return pageVisible;
}

export function useStartupWarmup(ready: boolean, warmupMs = STARTUP_BACKGROUND_WARMUP_MS): boolean {
  const [warmupActive, setWarmupActive] = useState(() => !ready);

  useEffect(() => {
    if (ready) {
      setWarmupActive(false);
      return;
    }
    setWarmupActive(true);
    if (warmupMs <= 0) {
      return;
    }
    const timer = window.setTimeout(() => {
      setWarmupActive(false);
    }, warmupMs);
    return () => {
      window.clearTimeout(timer);
    };
  }, [ready, warmupMs]);

  return warmupActive && !ready;
}

export function isBootStaggeredPollReady(
  ready: boolean,
  elapsedMs: number,
  delayMs = SHELL_DEFERRED_POLL_BOOT_DELAY_MS,
): boolean {
  if (!ready) {
    return false;
  }
  return delayMs <= 0 || elapsedMs >= delayMs;
}

/**
 * Boot-latch for chrome-only shell polls (git status badge, code freshness,
 * agent broadcast bell). Startup is a request volley: the route gate releases
 * the backlogged wave exactly when lifespan background tasks (registry repair,
 * git prewarm) start competing for the backend, so these non-critical badges
 * delay their first fetch a few seconds past shell-data-ready. The delay is a
 * per-mount boot latch: once elapsed it never re-applies, remounts included.
 */
export function useBootStaggeredPollReady(
  ready: boolean,
  delayMs = SHELL_DEFERRED_POLL_BOOT_DELAY_MS,
): boolean {
  const [elapsedSinceReadyMs, setElapsedSinceReadyMs] = useState(0);

  useEffect(() => {
    if (!ready || delayMs <= 0) {
      return;
    }
    const startedAt = Date.now();
    const timer = window.setTimeout(() => {
      setElapsedSinceReadyMs(Date.now() - startedAt);
    }, delayMs);
    return () => {
      window.clearTimeout(timer);
    };
  }, [ready, delayMs]);

  return isBootStaggeredPollReady(ready, elapsedSinceReadyMs, delayMs);
}
