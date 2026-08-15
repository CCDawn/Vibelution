import { PropsWithChildren } from "react";
import { useQuery } from "@tanstack/react-query";
import { Navigate } from "react-router-dom";

import { fetchPublicConfig } from "../api/config";
import { queryKeys } from "../api/queryKeys";
import { isWorkbenchModeEnabled, resolveWorkbenchHomePath, WorkbenchMode } from "../app/workbenchContract";

type WorkbenchModeRouteProps = PropsWithChildren<{
  mode: WorkbenchMode;
}>;

export function WorkbenchModeRoute({ mode, children }: WorkbenchModeRouteProps) {
  const configQuery = useQuery({
    queryKey: queryKeys.configPublic(),
    queryFn: () => fetchPublicConfig(),
  });

  if (configQuery.data && !isWorkbenchModeEnabled(configQuery.data, mode)) {
    return <Navigate to={resolveWorkbenchHomePath(configQuery.data)} replace />;
  }

  return <>{children}</>;
}
