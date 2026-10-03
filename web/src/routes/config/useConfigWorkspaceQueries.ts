/**
 * Config route workspace + diagnostics read queries.
 * Apply request body builders live in configApplyModel; wire handlers stay on ConfigRoute.
 */
import { useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { fetchConfigWorkspace } from "../../api/config";
import { fetchHealthDiagnostics } from "../../api/diagnostics";
import { queryKeys } from "../../api/queryKeys";

export function useConfigWorkspaceQueries() {
  const workspaceQuery = useQuery({
    queryKey: queryKeys.configWorkspace(),
    queryFn: ({ signal }) => fetchConfigWorkspace({ signal }),
  });
  return { workspaceQuery };
}

export function useConfigHealthDiagnosticsQuery(enabled: boolean) {
  const queryClient = useQueryClient();
  const healthDiagnosticsQuery = useQuery({
    queryKey: queryKeys.diagnosticsHealth(),
    queryFn: ({ signal }) => fetchHealthDiagnostics({ signal }),
    enabled,
  });
  // A mounted disabled observer does not abort a request by itself. Cancel only
  // inactive reads so another visible consumer of the same query stays intact.
  useEffect(() => {
    const cancelInactiveRead = () => {
      void queryClient.cancelQueries({ queryKey: queryKeys.diagnosticsHealth(), type: "inactive" });
    };
    if (!enabled) {
      cancelInactiveRead();
    }
    // Let query observers detach before checking the last visible consumer.
    return () => queueMicrotask(cancelInactiveRead);
  }, [enabled, queryClient]);
  return healthDiagnosticsQuery;
}
