import { useCallback, useMemo } from "react";
import {
  useQuery,
  type Query,
  type QueryFunctionContext,
  type QueryKey,
} from "@tanstack/react-query";

import { listPendingSessionToolApprovals } from "../../api/chat";
import { queryKeys } from "../../api/queryKeys";
import { mergeSessionDetailMessageWindow } from "../chatSessionState";
import type {
  SessionDetail,
  SessionSummary,
  SessionToolApprovalRequest,
} from "../../api/types";
import { isBusyPhase } from "./chatCodingRouteViewModel";
import { resolveSessionDetailPlaceholder } from "./chatSessionDetailHelpers";
import { resolveStickySessionDetailPaint } from "./chatSessionPaintCache";

/**
 * Stable sticky-placeholder for the active session-detail query.
 *
 * React Query's `forceStoreRerender`. Memoizing keeps the placeholder
 * reference identical while `activeSessionId`, the cached detail, and the
 * list summary are unchanged, and recomputes only when one of those inputs
 * actually changes.
 */
export function useStableSessionDetailPlaceholder(options: {
  activeSessionId: string | null | undefined;
  cachedDetail: SessionDetail | undefined;
  summary: SessionSummary | null | undefined;
}): SessionDetail | undefined {
  const { activeSessionId, cachedDetail, summary } = options;
  return useMemo(
    () => resolveSessionDetailPlaceholder({ activeSessionId, cachedDetail, summary }),
    [activeSessionId, cachedDetail, summary],
  );
}

/**
 * Stable structural-sharing merge for the active session-detail query.
 *
 * React Query keeps the `structuralSharing` option reference across renders;
 * an inline arrow rebuilt on every render handed the observer a fresh callback
 * each time and drove `forceStoreRerender` into the "Maximum update depth
 * exceeded" loop. Hoisting the merge to module scope fixes the identity while
 * preserving the exact `mergeSessionDetailMessageWindow` previous/next merge
 * semantics.
 */
export function sessionDetailStructuralSharing(
  previous: unknown,
  next: unknown,
): SessionDetail {
  return mergeSessionDetailMessageWindow(previous as SessionDetail | undefined, next as SessionDetail);
}

/**
 * Polling inputs that drive the pending tool-approvals observer.
 *
 * Shared by `useSessionToolApprovalsRefetchInterval` (which maps them to a
 * stable resolver reference) and `useSessionToolApprovalsQuery` (which owns the
 * whole observer). Keeping the inputs as one stable shape means an unrelated
 * parent rerender with identical inputs recomputes nothing.
 */
export type SessionToolApprovalPollingInput = {
  directSessionPanelActive: boolean;
  runtimeActive: boolean;
  detailCurrentPhase: string | undefined;
  summaryCurrentPhase: string | undefined;
  summaryStatus: string | undefined;
};

/**
 * Stable refetchInterval resolver for the pending tool-approvals poll.
 *
 * React Query re-derives the `refetchInterval` option while a poll runs, and
 * the previous inline closure rebuilt on every render, so each no-op parent
 * rerender handed the observer a fresh callback and reset the 2s timer in
 * lockstep — the same "Maximum update depth exceeded" `forceStoreRerender`
 * churn seen with the placeholder and structural-sharing seams. Hoisting the
 * resolver into `useCallback` keeps the reference identical while the polling
 * inputs (panel activity, busy inputs, detail/summary status) are unchanged,
 * and recomputes only when one of those inputs actually changes.
 */
export function useSessionToolApprovalsRefetchInterval(
  options: SessionToolApprovalPollingInput,
): (query: Query<SessionToolApprovalRequest[]>) => number | false {
  const {
    directSessionPanelActive,
    runtimeActive,
    detailCurrentPhase,
    summaryCurrentPhase,
    summaryStatus,
  } = options;
  return useCallback(
    (query) => {
      if (!directSessionPanelActive) {
        return false;
      }
      const hasPending = (query.state.data?.length ?? 0) > 0;
      // Avoid 250ms thrash while busy (queues behind heavy session-detail under load).
      // Pending approvals still poll sub-second; busy-without-pending is lighter.
      const busy = runtimeActive
        || isBusyPhase(detailCurrentPhase || summaryCurrentPhase || summaryStatus);
      if (hasPending) {
        return 750;
      }
      if (busy) {
        return 2_000;
      }
      return 4_000;
    },
    [
      directSessionPanelActive,
      runtimeActive,
      detailCurrentPhase,
      summaryCurrentPhase,
      summaryStatus,
    ],
  );
}

/**
 * Stable queryFn for the pending tool-approvals observer.
 *
 * Module scope: React Query re-derives the `queryFn` option on every parent
 * render. The previous inline arrow rebuilt each time and handed the observer a
 * fresh callback reference, so each no-op rerender re-triggered the same
 * `forceStoreRerender` churn already fixed for the placeholder /
 * structural-sharing / refetchInterval seams. Reading the sessionId from the
 * queryKey keeps this a single stable reference while still routing to the
 * active session; switching sessions re-keys the query so only the new session
 * is ever fetched.
 */
export function sessionToolApprovalsQueryFn(
  context: QueryFunctionContext<QueryKey>,
): Promise<SessionToolApprovalRequest[]> {
  return listPendingSessionToolApprovals(String(context.queryKey[1] ?? ""));
}

export type SessionToolApprovalsQueryOptions = {
  sessionId: string | null | undefined;
  enabled: boolean;
  polling: SessionToolApprovalPollingInput;
};

/**
 * Stable observer seam for the pending tool-approvals poll.
 *
 * Owns the queryKey/queryFn/refetchInterval configuration so an unrelated
 * parent rerender with the same `sessionId` and polling inputs cannot hand the
 * observer a fresh query identity, queryFn, or refetch callback and restart the
 * poll timer / trigger extra fetches. The queryKey is memoized per `sessionId`
 * so the observer's identity reference is stable, the queryFn is a module-scope
 * function, and the refetch resolver is `useCallback`-stable. `inactive=false`,
 * `pending=750`, `busy=2000` and `idle=4000` all come from
 * `useSessionToolApprovalsRefetchInterval`.
 */
export function useSessionToolApprovalsQuery(options: SessionToolApprovalsQueryOptions) {
  const { sessionId, enabled, polling } = options;
  const refetchInterval = useSessionToolApprovalsRefetchInterval(polling);
  const queryKey = useMemo(() => queryKeys.sessionToolApprovals(sessionId ?? "none"), [sessionId]);
  return useQuery<SessionToolApprovalRequest[]>({
    queryKey,
    enabled,
    queryFn: sessionToolApprovalsQueryFn,
    refetchInterval,
    refetchIntervalInBackground: false,
  });
}

/**
 * Stable sticky session-detail paint for the active session.
 *
 * `resolveStickySessionDetailPaint` rebuilds the merged sticky+live detail
 * (including a brand-new `messages` array) on every call. Called inline during
 * render, an unrelated parent rerender with the same `activeSessionId` and the
 * same `rawSessionDetail` reference handed downstream effects a fresh
 * detail/messages reference each time; the token-speed effect depended on
 * `detail.messages` and called `setTokenSpeedTracker`, and a single React Query
 * observer notification restarted the whole cycle until React bailed out with
 * "Maximum update depth exceeded" inside `forceStoreRerender`. Memoizing keeps
 * the detail (and its `messages` array) reference strictly identical while both
 * inputs are unchanged, and recomputes only when `activeSessionId` or the
 * resolved raw detail actually changes, preserving the existing sticky
 * transcript semantics. A query observer can still replay an equivalent raw
 * detail with a new reference; `updateTokenSpeedTracker` treats an unchanged
 * token count as a state no-op so that replay cannot feed another render back
 * into this observer cycle.
 */
export function useStableSessionDetailPaint(options: {
  activeSessionId: string | null | undefined;
  detail: SessionDetail | undefined;
}): SessionDetail | undefined {
  const { activeSessionId, detail: rawSessionDetail } = options;
  return useMemo(
    () => resolveStickySessionDetailPaint({ activeSessionId, detail: rawSessionDetail }),
    [activeSessionId, rawSessionDetail],
  );
}
