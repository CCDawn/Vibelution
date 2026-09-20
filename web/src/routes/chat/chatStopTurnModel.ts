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

export type StopTurnOptimisticContext = {
  previousDetail?: SessionDetail;
  stoppingAt?: string;
};

export type DeferredStopIntent = StopTurnOptimisticContext & {
  sessionId: string;
  clientSubmissionId?: string;
  /**
   * Filled by the mutation-cache listener when the acceptance arrives while
   * another session's stop request is still in flight.
   */
  acceptedTurnId?: string;
};

export function resolveStopOptimisticTarget(
  deferredStop: StopTurnOptimisticContext | undefined,
  cachedDetail: SessionDetail | undefined,
  now: string,
): { previousDetail: SessionDetail | undefined; stoppingAt: string } {
  const deferredStoppingAt = clean(deferredStop?.stoppingAt);
  if (deferredStoppingAt) {
    return { previousDetail: deferredStop?.previousDetail, stoppingAt: deferredStoppingAt };
  }
  return { previousDetail: cachedDetail, stoppingAt: now };
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
