import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { listVirtualHumanCompanions } from "../../api/agentPlugins";
import { queryKeys } from "../../api/queryKeys";
import { ChatRouteLoadingShell } from "../../app/ChatRouteLoadingShell";
import { companionRouteBindingIsVerified } from "./companionChatRouteIsolation";

export function CompanionChatRouteGate({ children }: { children: ReactNode }) {
  const location = useLocation();
  const params = new URLSearchParams(location.search);
  const requestedCompanionId = String(params.get("companion") || "").trim();
  const requestedSessionId = String(params.get("session") || "").trim();
  const requestedRoomId = String(params.get("room") || "").trim();
  const companionRouteRequested = Boolean(
    requestedCompanionId && requestedSessionId && !requestedRoomId,
  );
  const companionsQuery = useQuery({
    queryKey: queryKeys.virtualHumanCompanions(),
    queryFn: listVirtualHumanCompanions,
    enabled: companionRouteRequested,
    staleTime: 5_000,
  });

  if (!companionRouteRequested) return children;
  if (companionsQuery.isPending && !companionsQuery.data) {
    return <ChatRouteLoadingShell label="正在验证人物身份" />;
  }
  return companionRouteBindingIsVerified(
    companionsQuery.data,
    requestedCompanionId,
    requestedSessionId,
  ) ? children : <Navigate to="/companions" replace />;
}
