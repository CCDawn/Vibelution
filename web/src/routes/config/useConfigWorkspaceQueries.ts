/**
 * Config route workspace + diagnostics read queries.
 * Apply request body builders live in configApplyModel; wire handlers stay on ConfigRoute.
 */
import { useQuery } from "@tanstack/react-query";

import { fetchJson } from "../../api/client";
import { queryKeys } from "../../api/queryKeys";
import type { ConfigWorkspace, HealthDiagnostics } from "../../api/types";

export function useConfigWorkspaceQueries() {
  const workspaceQuery = useQuery({
    queryKey: queryKeys.configWorkspace(),
    queryFn: () => fetchJson<ConfigWorkspace>("/api/config/workspace"),
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
