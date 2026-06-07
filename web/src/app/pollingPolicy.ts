import { useEffect, useState } from "react";

export type PollingInterval = number | false;
export const STARTUP_BACKGROUND_WARMUP_MS = 45_000;

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
