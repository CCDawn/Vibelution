import { useQuery } from "@tanstack/react-query";
import { Navigate } from "react-router-dom";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import { ConfigSummary } from "../api/types";
import { resolveWorkbenchHomePath } from "../app/workbenchContract";
import { deriveQueryPresentation } from "../app/queryPresentation";
import { RouteLoadingShell } from "../app/RouteLoadingShell";
import { VButton, VStateSurface } from "../components/vui";

export function HomeRedirect() {
  const configQuery = useQuery({
    queryKey: queryKeys.configPublic(),
    queryFn: () => fetchJson<ConfigSummary>("/api/config/public"),
  });

  const presentation = deriveQueryPresentation({
    hasData: Boolean(configQuery.data),
    isError: configQuery.isError,
    isFetching: configQuery.isFetching,
    isPending: configQuery.isPending,
  });

  if (presentation === "initial-loading") {
    return <RouteLoadingShell label="正在确定默认工作台" meta="读取工作台配置" />;
  }

  if (presentation === "error-empty") {
    return (
      <VStateSurface
        tone="error"
        title="工作台配置读取失败"
        actions={<VButton type="button" onPress={() => void configQuery.refetch()}>重试</VButton>}
      >
        {configQuery.error instanceof Error ? configQuery.error.message : "无法确定默认工作台。"}
      </VStateSurface>
    );
  }

  return <Navigate to={resolveWorkbenchHomePath(configQuery.data)} replace />;
}
