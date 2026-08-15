/**
 * Config route workspace + diagnostics read queries.
 * Apply request body builders live in configApplyModel; wire handlers stay on ConfigRoute.
 */
import { useQuery } from "@tanstack/react-query";

import { fetchJson } from "../../api/client";
import { fetchConfigWorkspace } from "../../api/config";
import { queryKeys } from "../../api/queryKeys";
import type { HealthDiagnostics } from "../../api/types";

export function useConfigWorkspaceQueries() {
  const workspaceQuery = useQuery({
    queryKey: queryKeys.configWorkspace(),
    queryFn: () => fetchConfigWorkspace(),
  });
  const healthDiagnosticsQuery = useQuery({
    queryKey: queryKeys.diagnosticsHealth(),
    queryFn: () => fetchJson<HealthDiagnostics>("/api/diagnostics/health"),
  });
  return {
    workspaceQuery,
    healthDiagnosticsQuery,
  };
}
