import { type QueryClient, type UseMutationResult } from "@tanstack/react-query";
import { useRef } from "react";
import type { Dispatch, MutableRefObject, SetStateAction } from "react";

import {
  type AgentDirectSessionResetResponse,
} from "../../api/agents";
import { startUserAction } from "../../app/userActionTelemetry";
import type {
  AgentInstance,
  ChatRoomDetail,
  ChatRoomRoundAcceptedResponse,
  SessionChatReviewCandidateResponse,
  SessionDeleteResponse,
  SessionBulkDeleteResponse,
  SessionDetail,
  SessionSummary,
} from "../../api/types";
import type { TranslationKey } from "../../i18n/dictionary";
import {
  captureAgentSessionCacheSnapshots,
  captureSessionIndexCacheSnapshots,
} from "../chatSessionIndexQuery";
import type { createChatWorkspaceCache } from "../chatWorkspaceCache";
import { useChatSessionChangeMutations } from "./useChatSessionChangeMutations";
import {
  useChatGroupWorkspaceMutations,
} from "./useChatGroupWorkspaceMutations";
import type { ChatRouteSelection } from "./chatSelectionProjection";
import {
  useChatSessionCreateMutation,
  type SessionCreateMutationContext,
  type SessionCreateVariables,
} from "./useChatSessionCreateMutation";

type ChatWorkspaceCache = ReturnType<typeof createChatWorkspaceCache>;
type RightIndexPanel = "conversations" | "members";
type ChatRouteLifecycleActions = {
  openSession: (sessionId: string) => void;
  openRoom: (roomId: string) => void;
  replaceIfStillViewing: (expected: ChatRouteSelection, next: ChatRouteSelection) => boolean;
};

export type { AgentDirectSessionResetResponse };

export type UseChatWorkspaceLifecycleOptions = {
  queryClient: QueryClient;
  chatWorkspaceCache: ChatWorkspaceCache;
  lang: "zh" | "en";
  t: (key: TranslationKey) => string;
  describeError: (error: unknown, fallback: string) => string;
  syncSessionDetail: (detail: SessionDetail) => void;
  syncChatRoomDetail: (room: ChatRoomDetail) => void;
  clearSessionTransientUiState: (sessionId: string) => void;
  removeSessionWorkspace: (sessionId: string) => void;
  rebaseSessionComposerState: (fromId: string, toId: string) => void;
  requestSessionComposerFocus: (sessionId: string) => void;
  /** Always-current committed route selection (snapshot at request start). */
  routeSelectionRef: MutableRefObject<ChatRouteSelection>;
  /** Sole Chat route writer (compare-and-swap transitions only). */
  chatRoute: ChatRouteLifecycleActions;
  setRightIndexPanel: Dispatch<SetStateAction<RightIndexPanel>>;
  setSelectedAgentId: Dispatch<SetStateAction<string>>;
  setSessionFilter: Dispatch<SetStateAction<string>>;
  setSessionComposerErrors: Dispatch<SetStateAction<Record<string, string>>>;
  setGroupComposerOpen: Dispatch<SetStateAction<boolean>>;
  setGroupTitleDraft: Dispatch<SetStateAction<string>>;
  setGroupModeDraft: Dispatch<SetStateAction<string>>;
  setGroupPurposeDraft: Dispatch<SetStateAction<string>>;
  setGroupSelectedAgentIds: Dispatch<SetStateAction<string[]>>;
  setGroupTopicDraft: Dispatch<SetStateAction<string>>;
  setGroupRoomActionError: Dispatch<SetStateAction<string>>;
  setGroupManageTitleDraft: Dispatch<SetStateAction<string>>;
  setGroupManageSessionIds: Dispatch<SetStateAction<string[]>>;
  setGroupManageModeDraft: Dispatch<SetStateAction<string>>;
  setGroupManagePurposeDraft: Dispatch<SetStateAction<string>>;
  setProjectBusDraft: Dispatch<SetStateAction<string>>;
  editingSessionIdRef: MutableRefObject<string | null>;
  /** Live rename draft; only set while the operator is editing a tab title. */
  editingSessionTitleRef: MutableRefObject<string>;
  setEditingSessionId: Dispatch<SetStateAction<string | null>>;
  setEditingSessionTitle: Dispatch<SetStateAction<string>>;
  /** Ignore rename blur for a short window while a temp→real remap remounts an open editor. */
  suppressRenameBlurUntilRef: MutableRefObject<number>;
};

export type UseChatWorkspaceLifecycleResult = {
  createSessionMutation: UseMutationResult<
    SessionDetail,
    Error,
    SessionCreateVariables,
    SessionCreateMutationContext
  >;
  createGroupRoomMutation: UseMutationResult<
    ChatRoomDetail,
    Error,
    { title: string; agentIds: string[]; mode: string; purpose: string },
    {
      routeSelectionAtRequest: ChatRouteSelection;
      tempRoomId: string;
      telemetry: ReturnType<typeof startUserAction>;
    }
  >;
  startGroupRoundMutation: UseMutationResult<
    ChatRoomRoundAcceptedResponse,
    Error,
    { roomId: string; topic: string; mode: string; purpose: string },
    unknown
  >;
  stopGroupRoundMutation: UseMutationResult<ChatRoomDetail, Error, { roomId: string }, unknown>;
  sendProjectBusMessageMutation: UseMutationResult<
    unknown,
    Error,
    { content: string; interruptTargets: boolean },
    unknown
  >;
  revokeProjectBusMessageMutation: UseMutationResult<unknown, Error, { eventId: string }, unknown>;
  updateGroupRoomMutation: UseMutationResult<
    ChatRoomDetail,
    Error,
    { roomId: string; title: string; sessionIds: string[]; mode: string; purpose: string },
    unknown
  >;
  deleteGroupRoomMutation: UseMutationResult<
    { deleted: boolean; roomId: string },
    Error,
    { roomId: string },
    unknown
  >;
  resetGroupRoomMutation: UseMutationResult<ChatRoomDetail, Error, { roomId: string }, unknown>;
  deleteSessionMutation: UseMutationResult<
    SessionDeleteResponse,
    Error,
    { sessionId: string },
    {
      previousSessions: SessionSummary[] | undefined;
      previousSessionIndexCaches: ReturnType<typeof captureSessionIndexCacheSnapshots>;
      previousAgentSessionCaches: ReturnType<typeof captureAgentSessionCacheSnapshots>;
      previousAgents: AgentInstance[] | undefined;
      deletedAgentId: string;
    }
  >;
  bulkDeleteSessionsMutation: UseMutationResult<
    SessionBulkDeleteResponse,
    Error,
    { sessionIds: string[] },
    {
      previousSessions: SessionSummary[] | undefined;
      previousSessionIndexCaches: ReturnType<typeof captureSessionIndexCacheSnapshots>;
      previousAgentSessionCaches: ReturnType<typeof captureAgentSessionCacheSnapshots>;
      previousAgents: AgentInstance[] | undefined;
      previousRouteSessionId: string;
      deletedSessionIds: string[];
      optimisticNextActiveSessionId: string;
      telemetry: ReturnType<typeof startUserAction>;
    }
  >;
  clearSessionHistoryMutation: UseMutationResult<
    AgentDirectSessionResetResponse,
    Error,
    { sessionId: string; agentId: string },
    unknown
  >;
  renameSessionMutation: UseMutationResult<
    SessionDetail,
    Error,
    { sessionId: string; title: string },
    {
      previousSessions: SessionSummary[] | undefined;
      previousSessionIndexCaches: ReturnType<typeof captureSessionIndexCacheSnapshots>;
      previousAgentSessionCaches: ReturnType<typeof captureAgentSessionCacheSnapshots>;
      previousDetail: SessionDetail | undefined;
      optimisticUpdatedAt: string;
      attemptId: symbol;
    }
  >;
  addSessionToReviewMutation: UseMutationResult<
    SessionChatReviewCandidateResponse,
    Error,
    { sessionId: string },
    unknown
  >;
};

/**
 * Chat workspace lifecycle mutations: session create, session changes, and
 * group workspace actions. Session create lives in useChatSessionCreateMutation.
 * Does not open EventSources.
 */
export function useChatWorkspaceLifecycle({
  queryClient,
  chatWorkspaceCache,
  lang,
  t,
  describeError,
  syncSessionDetail,
  syncChatRoomDetail,
  clearSessionTransientUiState,
  removeSessionWorkspace,
  rebaseSessionComposerState,
  requestSessionComposerFocus,
  routeSelectionRef,
  chatRoute,
  setRightIndexPanel,
  setSelectedAgentId,
  setSessionFilter,
  setSessionComposerErrors,
  setGroupComposerOpen,
  setGroupTitleDraft,
  setGroupModeDraft,
  setGroupPurposeDraft,
  setGroupSelectedAgentIds,
  setGroupTopicDraft,
  setGroupRoomActionError,
  setGroupManageTitleDraft,
  setGroupManageSessionIds,
  setGroupManageModeDraft,
  setGroupManagePurposeDraft,
  setProjectBusDraft,
  editingSessionIdRef,
  editingSessionTitleRef,
  setEditingSessionId,
  setEditingSessionTitle,
  suppressRenameBlurUntilRef,
}: UseChatWorkspaceLifecycleOptions): UseChatWorkspaceLifecycleResult {
  type RenameContext = NonNullable<UseChatWorkspaceLifecycleResult["renameSessionMutation"]["context"]>;
  // Keep only overlapping attempts. Failed snapshots must unwind in submission
  // order even when the failures arrive in the opposite order.
  const renameAttemptsRef = useRef(new Map<string, Array<{
    variables: { sessionId: string; title: string };
    context: RenameContext;
    outcome: "pending" | "succeeded" | "failed";
  }>>());
  const {
    createSessionMutation,
    createSessionIntentsRef,
    forgetCreateSessionIntent,
  } = useChatSessionCreateMutation({
    queryClient,
    lang,
    t,
    describeError,
    syncSessionDetail,
    removeSessionWorkspace,
    rebaseSessionComposerState,
    routeSelectionRef,
    chatRoute,
    setRightIndexPanel,
    setSelectedAgentId,
    setSessionFilter,
    setSessionComposerErrors,
    editingSessionIdRef,
    editingSessionTitleRef,
    setEditingSessionId,
    setEditingSessionTitle,
    suppressRenameBlurUntilRef,
  });

  const {
    createGroupRoomMutation,
    startGroupRoundMutation,
    stopGroupRoundMutation,
    sendProjectBusMessageMutation,
    revokeProjectBusMessageMutation,
    updateGroupRoomMutation,
    deleteGroupRoomMutation,
    resetGroupRoomMutation,
  } = useChatGroupWorkspaceMutations({
    queryClient,
    chatWorkspaceCache,
    lang,
    describeError,
    syncChatRoomDetail,
    routeSelectionRef,
    chatRoute,
    setRightIndexPanel,
    setSessionFilter,
    setSessionComposerErrors,
    setGroupComposerOpen,
    setGroupTitleDraft,
    setGroupModeDraft,
    setGroupPurposeDraft,
    setGroupSelectedAgentIds,
    setGroupTopicDraft,
    setGroupRoomActionError,
    setGroupManageTitleDraft,
    setGroupManageSessionIds,
    setGroupManageModeDraft,
    setGroupManagePurposeDraft,
    setProjectBusDraft,
  });

  const {
    deleteSessionMutation,
    bulkDeleteSessionsMutation,
    clearSessionHistoryMutation,
    renameSessionMutation,
    addSessionToReviewMutation,
  } = useChatSessionChangeMutations({
    queryClient,
    chatWorkspaceCache,
    lang,
    t,
    describeError,
    clearSessionTransientUiState,
    removeSessionWorkspace,
    requestSessionComposerFocus,
    routeSelectionRef,
    chatRoute,
    setSessionComposerErrors,
    setGroupManageSessionIds,
    editingSessionIdRef,
    setEditingSessionId,
    setEditingSessionTitle,
    createSessionIntentsRef,
    forgetCreateSessionIntent,
    renameAttemptsRef,
  });

  return {
    createSessionMutation,
    createGroupRoomMutation,
    startGroupRoundMutation,
    stopGroupRoundMutation,
    sendProjectBusMessageMutation,
    revokeProjectBusMessageMutation,
    updateGroupRoomMutation,
    deleteGroupRoomMutation,
    resetGroupRoomMutation,
    deleteSessionMutation,
    bulkDeleteSessionsMutation,
    clearSessionHistoryMutation,
    renameSessionMutation,
    addSessionToReviewMutation,
  };
}
