import { useEffect, useState } from "react";

export type PollingInterval = number | false;

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
