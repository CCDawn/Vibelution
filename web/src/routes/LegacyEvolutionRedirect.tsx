import { useQuery } from "@tanstack/react-query";
import { Navigate } from "react-router-dom";

import { fetchPublicConfig } from "../api/config";
import { queryKeys } from "../api/queryKeys";
import { resolveEvolutionHomePath } from "../app/workbenchContract";

export function LegacyEvolutionRedirect() {
  const configQuery = useQuery({
    queryKey: queryKeys.configPublic(),
    queryFn: () => fetchPublicConfig(),
  });

  if (!configQuery.data && !configQuery.isError) {
    return null;
  }

  return <Navigate to={resolveEvolutionHomePath(configQuery.data)} replace />;
}
