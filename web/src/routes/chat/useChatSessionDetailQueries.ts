/**
 * Active-session detail, LLM options, and child-session queries, plus the
 * startup-ready and focus-resync effects that key off those queries.
 * Live policy is still decided by the workbench; this hook only reads it.
 */
import { useQuery, type QueryClient } from "@tanstack/react-query";
import { useEffect, useRef, type Dispatch, type MutableRefObject, type SetStateAction } from "react";

import { fetchSessionBudgetParameters, fetchSessionLlmOptions, listSessionChildSessions } from "../../api/chat";
import { queryKeys } from "../../api/queryKeys";
import type { ChatRoomDetail, SessionDetail, SessionSummary } from "../../api/types";
import { postBrowserTelemetry } from "../../app/browserTelemetry";
import { isVisibleDirectSession, rootSessionIdFor } from "../conversationIndexModel";
import { isTempSessionId } from "../sessionOptimisticIds";
import {
  resolveChatLiveQueryPolicy,
  type ChatLiveQueryPolicy,
  type ChatLiveQueryPolicyInput,
} from "../chatLiveQueryPolicy";
import { fetchSessionDetailWindow, isProvisionalSessionTranscript } from "./chatSessionDetailHelpers";
import {
  sessionDetailStructuralSharing,
  useStableSessionDetailPlaceholder,
} from "./chatSessionQuerySeams";
import type { SessionStreamDecisionSnapshot } from "./chatSessionStreamConnect";
import { isBusyPhase } from "./chatCodingRouteViewModel";
import { canLoadSessionParameters } from "./chatSessionSurfaceModel";

/** Wait for the same visible directory used by bare-route canonicalization. */
export function shouldWaitForChatStartupRestore(options: {
  bareRoute: boolean;
  routeVisibleSessions: SessionSummary[] | undefined;
  agentDirectoryFailed: boolean;
  directoryGatePending?: boolean;
}): boolean {
  if (!options.bareRoute) return false;
  if (options.directoryGatePending) return true;
  if (!options.routeVisibleSessions) return !options.agentDirectoryFailed;
  return options.routeVisibleSessions.some((session) => isVisibleDirectSession(session));
}

export type UseChatSessionDetailQueriesInput = {
  activeSessionId: string | null;
  bareRouteRestorePending: boolean;
  queryClient: QueryClient;
  sessions: SessionSummary[] | undefined;
  directSessionActiveSummary: SessionSummary | undefined;
  chatLiveQueryPolicy: ChatLiveQueryPolicy;
  chatLiveQueryPolicyInput: ChatLiveQueryPolicyInput;
  secondaryChatDataEnabled: boolean;
  directSessionPanelActive: boolean;
  standardGroupRoomActive: boolean;
  activeGroupRoom: ChatRoomDetail | null | undefined;
  financeSurface: boolean;
  runtime: unknown;
  conversations: unknown;
  teams: unknown;
  pageVisible: boolean;
  chatStartupDataReady: boolean;
  startupDetailSettledSessionId: string;
  setStartupDetailSettledSessionId: Dispatch<SetStateAction<string>>;
  setChatStartupDataReady: Dispatch<SetStateAction<boolean>>;
  setDirectSessionBackgroundSyncActive: Dispatch<SetStateAction<boolean>>;
  chatRouteMountStartedAtRef: MutableRefObject<number>;
  chatRouteStartupReadyLoggedRef: MutableRefObject<boolean>;
  sessionStreamDecisionSnapshotRef: MutableRefObject<SessionStreamDecisionSnapshot>;
};

export function useChatSessionDetailQueries({
  activeSessionId,
  bareRouteRestorePending,
  queryClient,
  sessions,
  directSessionActiveSummary,
  chatLiveQueryPolicy,
  chatLiveQueryPolicyInput,
  secondaryChatDataEnabled,
  directSessionPanelActive,
  standardGroupRoomActive,
  activeGroupRoom,
  financeSurface,
  runtime,
  conversations,
  teams,
  pageVisible,
  chatStartupDataReady,
  startupDetailSettledSessionId,
  setStartupDetailSettledSessionId,
  setChatStartupDataReady,
  setDirectSessionBackgroundSyncActive,
  chatRouteMountStartedAtRef,
  chatRouteStartupReadyLoggedRef,
  sessionStreamDecisionSnapshotRef,
}: UseChatSessionDetailQueriesInput) {
  const sessionDetailPlaceholder = useStableSessionDetailPlaceholder({
    activeSessionId,
    cachedDetail: queryClient.getQueryData<SessionDetail>(queryKeys.session(activeSessionId ?? "none")),
    summary: activeSessionId
      ? sessions?.find((session) => session.id === activeSessionId)
      : undefined,
  });
  const sessionDetailQuery = useQuery<SessionDetail>({
    queryKey: queryKeys.session(activeSessionId ?? "none"),
    // Temp create shells are local-only; never GET/stream them until rebased.
    enabled: Boolean(activeSessionId) && !isTempSessionId(activeSessionId),
    queryFn: ({ signal }) => fetchSessionDetailWindow(activeSessionId, {
      signal,
      // When SSE owns live transcript, skip expensive secondary lists on poll/refetch.
      // First paint still hydrates fully until stream ownership is true.
      includeSecondary: !chatLiveQueryPolicy.directSessionStreamOwnsLiveQueries,
    }),
    // Select + GET often race on switch; brief freshness avoids immediate double rebuild
    // when /select already wrote a windowed detail into the same query key.
    staleTime: 1_500,
    structuralSharing: sessionDetailStructuralSharing,
    placeholderData: sessionDetailPlaceholder,
    refetchInterval: startupDetailSettledSessionId === activeSessionId
      ? chatLiveQueryPolicy.sessionDetailRefetchInterval
      : false,
    refetchIntervalInBackground: chatLiveQueryPolicy.directRefetchIntervalInBackground,
  });
  useEffect(() => {
    if (!activeSessionId) {
      setStartupDetailSettledSessionId("");
      return;
    }
    if (sessionDetailQuery.isError) {
      setStartupDetailSettledSessionId((current) => current === activeSessionId ? current : activeSessionId);
      return;
    }
    if (
      sessionDetailQuery.isFetching
      || !sessionDetailQuery.data
      || sessionDetailQuery.data.id !== activeSessionId
      || (!isTempSessionId(activeSessionId) && (
        sessionDetailQuery.isPlaceholderData || isProvisionalSessionTranscript(sessionDetailQuery.data)
      ))
    ) {
      return;
    }
    setStartupDetailSettledSessionId((current) => current === activeSessionId ? current : activeSessionId);
  }, [activeSessionId, sessionDetailQuery.data, sessionDetailQuery.isError, sessionDetailQuery.isFetching, sessionDetailQuery.isPlaceholderData, setStartupDetailSettledSessionId]);
  const sessionLlmOptionsQuery = useQuery({
    queryKey: queryKeys.sessionLlmOptions(activeSessionId ?? "none"),
    enabled: secondaryChatDataEnabled && canLoadSessionParameters(activeSessionId, sessionDetailQuery.data) && !isTempSessionId(activeSessionId),
    queryFn: () => fetchSessionLlmOptions(activeSessionId ?? ""),
    staleTime: 30_000,
    // Re-read the Agent binding when returning from Agent management.
    refetchOnMount: "always",
  });
  // Per-session budget parameters feed the composer plus-menu budget dialog.
  // Finance surfaces keep their own assistant pipeline, so they skip the fetch.
  const sessionBudgetParametersQuery = useQuery({
    queryKey: queryKeys.sessionBudgetParameters(activeSessionId ?? "none"),
    enabled: (
      secondaryChatDataEnabled
      && !financeSurface
      && canLoadSessionParameters(activeSessionId, sessionDetailQuery.data)
      && Boolean(activeSessionId)
      && !isTempSessionId(activeSessionId)
    ),
    queryFn: () => fetchSessionBudgetParameters(activeSessionId ?? ""),
    staleTime: 30_000,
    // Revisions move with every save; always re-read on surface entry.
    refetchOnMount: "always",
  });
  // Explicit missing/archived session keeps its URL and renders the blocking
  // unavailable surface. Background misses must never fall back to another
  // session and must never navigate.
  const activeRootSessionId = rootSessionIdFor(sessionDetailQuery.data ?? directSessionActiveSummary);
  const childSessionLiveQueryPolicy = resolveChatLiveQueryPolicy({
    ...chatLiveQueryPolicyInput,
    activeRootSessionId: activeRootSessionId || "",
  });
  const childSessionsQuery = useQuery({
    queryKey: queryKeys.sessionChildSessions(activeRootSessionId || "none"),
    queryFn: () => listSessionChildSessions(activeRootSessionId),
    enabled: secondaryChatDataEnabled && Boolean(activeRootSessionId) && directSessionPanelActive,
    refetchInterval: childSessionLiveQueryPolicy.childSessionsRefetchInterval,
    refetchIntervalInBackground: childSessionLiveQueryPolicy.directRefetchIntervalInBackground,
  });
  useEffect(() => {
    // A summary shell can paint the frame, but the initial transcript still
    // needs the connection slots that secondary catalogs would otherwise take.
    const directReady = activeSessionId
      ? sessionDetailQuery.isError || Boolean(sessionDetailQuery.data?.id === activeSessionId && (
          isTempSessionId(activeSessionId)
          || (!sessionDetailQuery.isPlaceholderData && !isProvisionalSessionTranscript(sessionDetailQuery.data))
        ))
      : Boolean(sessions) && !bareRouteRestorePending;
    const groupReady = !standardGroupRoomActive || Boolean(activeGroupRoom);
    if ((financeSurface || sessions) && directReady && groupReady) {
      setChatStartupDataReady(true);
    }
  }, [
    activeGroupRoom,
    activeSessionId,
    bareRouteRestorePending,
    financeSurface,
    sessionDetailQuery.data,
    sessionDetailQuery.isError,
    sessionDetailQuery.isPlaceholderData,
    sessions,
    setChatStartupDataReady,
    standardGroupRoomActive,
  ]);
  useEffect(() => {
    if (!chatStartupDataReady || chatRouteStartupReadyLoggedRef.current) {
      return;
    }
    chatRouteStartupReadyLoggedRef.current = true;
    postBrowserTelemetry({
      phase: "navigation",
      eventCode: sessionDetailQuery.isError ? "browser.chat_route.startup_data_failed" : "browser.chat_route.startup_data_ready",
      message: sessionDetailQuery.isError ? "Chat route startup reached a detail error surface." : "Chat route startup data is ready.",
      fields: {
        durationMs: Math.max(0, Date.now() - chatRouteMountStartedAtRef.current),
        activeSession: Boolean(activeSessionId),
        standardGroupRoomActive,
        runtimeReady: Boolean(runtime),
        sessionsReady: Boolean(sessions),
        conversationsReady: Boolean(conversations),
        teamsReady: Boolean(teams),
        sessionDetailReady: Boolean(activeSessionId ? sessionDetailQuery.data : true),
        groupRoomReady: Boolean(!standardGroupRoomActive || activeGroupRoom),
      },
    });
  }, [
    activeGroupRoom,
    activeSessionId,
    chatRouteMountStartedAtRef,
    chatRouteStartupReadyLoggedRef,
    chatStartupDataReady,
    conversations,
    runtime,
    sessionDetailQuery.data,
    sessionDetailQuery.isError,
    sessions,
    standardGroupRoomActive,
    teams,
  ]);
  useEffect(() => {
    setDirectSessionBackgroundSyncActive(Boolean(
      activeSessionId
      && directSessionPanelActive
      && isBusyPhase(sessionDetailQuery.data?.currentPhase || directSessionActiveSummary?.currentPhase || directSessionActiveSummary?.status),
    ));
  }, [
    activeSessionId,
    directSessionActiveSummary?.currentPhase,
    directSessionActiveSummary?.status,
    directSessionPanelActive,
    sessionDetailQuery.data?.currentPhase,
    setDirectSessionBackgroundSyncActive,
  ]);
  // A hidden window can miss frames or a stream restart; refocusing must not
  // trust the cached transcript, so force one authoritative resync for the
  // active session and the indexes that feed badges and notification titles.
  const previousPageVisibleRef = useRef(pageVisible);
  const refetchSessionDetailRef = useRef(sessionDetailQuery.refetch);
  refetchSessionDetailRef.current = sessionDetailQuery.refetch;
  const focusResyncSessionIdRef = useRef(activeSessionId || "");
  focusResyncSessionIdRef.current = activeSessionId || "";
  useEffect(() => {
    const previousPageVisible = previousPageVisibleRef.current;
    previousPageVisibleRef.current = pageVisible;
    const resyncSessionId = focusResyncSessionIdRef.current;
    if (!pageVisible || previousPageVisible || !resyncSessionId) {
      return;
    }
    // enabled:false does not stop refetch(). A temp shell has no server row;
    // this GET 404s and the error surface replaces the composer.
    if (!isTempSessionId(resyncSessionId)) {
      void refetchSessionDetailRef.current();
    }
    void queryClient.invalidateQueries({ queryKey: queryKeys.sessions() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.conversations() });
    postBrowserTelemetry({
      phase: "session_stream",
      eventCode: "browser.session_stream.focus_resync",
      message: "Focus after a hidden period forced an authoritative session resync.",
      level: "info",
      fields: {
        sessionId: resyncSessionId,
        streamShouldConnect: sessionStreamDecisionSnapshotRef.current.shouldConnect,
        visibilityState: typeof document === "undefined" ? "unknown" : document.visibilityState,
      },
    });
  }, [pageVisible, queryClient, sessionStreamDecisionSnapshotRef]);

  return {
    sessionDetailQuery,
    sessionLlmOptionsQuery,
    sessionBudgetParametersQuery,
    activeRootSessionId,
    childSessionsQuery,
  };
}
