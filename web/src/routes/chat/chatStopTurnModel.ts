import type { QueryClient } from "@tanstack/react-query";

import { queryKeys } from "../../api/queryKeys";
import type { SessionDetail } from "../../api/types";
import { latestUserTurnId } from "../chatActiveTurnLayer";

function clean(value: unknown) {
  return String(value ?? "").trim();
}

export function resolveSessionStopTurnId(
  detail: SessionDetail | undefined,
  activeLayerTurnId = "",
) {
  const activeTurnId = clean(activeLayerTurnId);
  if (activeTurnId) {
    return activeTurnId.startsWith("optimistic-") ? "" : activeTurnId;
  }
  return clean(detail?.activeTurnId) || latestUserTurnId(detail);
}

export function sessionStopRequestBody(turnId: string) {
  const normalizedTurnId = clean(turnId);
  if (!normalizedTurnId) {
    return undefined;
  }
  return JSON.stringify({ turnId: normalizedTurnId });
}

export function congestedQueryKeysForSessionStop(sessionId: string) {
  const normalizedSessionId = clean(sessionId);
  return [
    queryKeys.conversations(),
    queryKeys.sessions(),
    queryKeys.session(normalizedSessionId),
    queryKeys.launcherBranchInstances(),
    queryKeys.launcherStatus(),
    queryKeys.gitStatus(),
    queryKeys.agents(),
  ] as const;
}

export async function cancelCongestedQueriesForSessionStop(
  queryClient: QueryClient,
  sessionId: string,
) {
  await Promise.all(
    congestedQueryKeysForSessionStop(sessionId).map((queryKey) => queryClient.cancelQueries({ queryKey })),
  );
}
