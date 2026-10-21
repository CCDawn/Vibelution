import { createContext, useContext, useEffect } from "react";

/** A route reports when its initial data has either loaded or reached an error surface. */
export const WorkbenchStartupReadyContext = createContext<(() => void) | null>(null);

export function useReportWorkbenchStartupReady(
  ready: boolean,
  startupQueries: readonly { isError: boolean }[] = [],
): void {
  const reportReady = useContext(WorkbenchStartupReadyContext);
  const settled = ready || startupQueries.some((query) => query.isError);
  useEffect(() => {
    if (settled) reportReady?.();
  }, [reportReady, settled]);
}
