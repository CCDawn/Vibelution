import { type QueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { queryKeys } from "../api/queryKeys";

export const UPDATE_FRESHNESS_INTERVAL_MS = 60_000;
export const UPDATE_FRESHNESS_QUERY_OPTIONS = {
  staleTime: 30_000,
  refetchOnMount: "always" as const,
  refetchOnWindowFocus: "always" as const,
  refetchIntervalInBackground: false,
};

/** Re-read both owners; invalidation never substitutes a successful update verdict. */
export async function refreshUpdateFreshness(client: QueryClient, cancelRefetch = true): Promise<void> {
  await Promise.all([
    client.invalidateQueries({ queryKey: queryKeys.codeFreshness() }, { cancelRefetch }),
    client.invalidateQueries({ queryKey: queryKeys.launcherFreshness() }, { cancelRefetch }),
  ]);
}

/** React Query v5 observes visibility, but Electron can focus an already visible window. */
export function useUpdateFreshnessFocus(client: QueryClient, enabled: boolean): void {
  useEffect(() => {
    if (!enabled) return;
    const refresh = () => { void refreshUpdateFreshness(client, false); };
    window.addEventListener("focus", refresh);
    window.addEventListener("pageshow", refresh);
    return () => {
      window.removeEventListener("focus", refresh);
      window.removeEventListener("pageshow", refresh);
    };
  }, [client, enabled]);
}
