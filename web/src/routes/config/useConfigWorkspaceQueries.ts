/**
 * Config route workspace + diagnostics read queries.
 * Apply request body builders live in configApplyModel; wire handlers stay on ConfigRoute.
 */
import { useQuery } from "@tanstack/react-query";

import { fetchConfigWorkspace } from "../../api/config";
import { fetchHealthDiagnostics } from "../../api/diagnostics";
import { queryKeys } from "../../api/queryKeys";

export function useConfigWorkspaceQueries() {
  const workspaceQuery = useQuery({
    queryKey: queryKeys.configWorkspace(),
    queryFn: () => fetchConfigWorkspace(),
  });
  const healthDiagnosticsQuery = useQuery({
    queryKey: queryKeys.diagnosticsHealth(),
    queryFn: () => fetchHealthDiagnostics(),
  });
  return {
    workspaceQuery,
    healthDiagnosticsQuery,
  };
}
