import { useCallback, type Dispatch, type SetStateAction } from "react";
import type { QueryClient } from "@tanstack/react-query";

import type {
  AgentInstance,
  ChatRoomDetail,
  SessionSummary,
} from "../../api/types";
import type { TranslationKey } from "../../i18n/dictionary";
import { isAgentRootSession } from "../DirectSessionIndexItem";
import type { ChatMentionTarget } from "../chatMentionTokens";
import type { createChatWorkspaceCache } from "../chatWorkspaceCache";
import { isTempSessionId } from "../sessionOptimisticIds";
import { prefetchSessionDetailWindow } from "./chatSessionDetailHelpers";
import { isBusyPhase } from "./chatCodingRouteViewModel";
import type { UseChatRouteSelectionResult } from "./useChatRouteSelection";
import {
  chatAgentSessionStorage,
  lastSessionForAgent,
  readAgentLastSessionMap,
  rememberAgentLastSession,
  resolveAgentOpenSessionId,
} from "./chatAgentSessionMemory";

type ChatWorkspaceCache = ReturnType<typeof createChatWorkspaceCache>;
type RightIndexPanel = "conversations" | "members";
type PetInteractionAction = "feed" | "talk" | "care";

type MutateLike<TVariables> = {
  mutate: (variables: TVariables) => void;
  isPending: boolean;
  variables?: TVariables;
};

type ChatRouteActions = Pick<
  UseChatRouteSelectionResult,
  "openSession" | "openRoom" | "openProjectBus"
>;

export type UseChatWorkspaceActionsOptions = {
  lang: "zh" | "en";
  t: (key: TranslationKey) => string;
  chatRoute: ChatRouteActions;
  queryClient: QueryClient;
  chatWorkspaceCache: ChatWorkspaceCache;
  setRightIndexPanel: Dispatch<SetStateAction<RightIndexPanel>>;
  setRightPaneCollapsed: Dispatch<SetStateAction<boolean>>;
  setSelectedAgentId: Dispatch<SetStateAction<string>>;
  setSessionFilter: Dispatch<SetStateAction<string>>;
  setSessionComposerErrors: Dispatch<SetStateAction<Record<string, string>>>;
  setSessionContextMenu: Dispatch<SetStateAction<{ sessionId: string; session: SessionSummary; x: number; y: number } | null>>;
  setGroupRoomActionError: Dispatch<SetStateAction<string>>;
  setGroupComposerOpen: Dispatch<SetStateAction<boolean>>;
  setGroupTitleDraft: Dispatch<SetStateAction<string>>;
  groupTitleDraft: string;
  groupModeDraft: string;
  groupPurposeDraft: string;
  groupSelectedAgentIds: string[];
  setGroupSelectedAgentIds: Dispatch<SetStateAction<string[]>>;
  groupTopicDraft: string;
  projectBusDraft: string;
  projectBusInterruptTargets: boolean;
  setGroupManageSessionIds: Dispatch<SetStateAction<string[]>>;
  groupManageTitleDraft: string;
  groupManageSessionIds: string[];
  groupManageModeDraft: string;
  groupManagePurposeDraft: string;
  selectedChatAgentId: string;
  sessionsById?: ReadonlyMap<string, Pick<SessionSummary, "id" | "agentId">>;
  standardGroupRoomActive: boolean;
  activeGroupTeamOwned: boolean;
  groupRoundActive: boolean;
  groupRoundRunning: boolean;
  groupManageDisabled: boolean;
  groupDeleteDisabled: boolean;
  groupResetDisabled: boolean;
  activeGroupRoom: ChatRoomDetail | null | undefined;
  setPetActionFeedback: Dispatch<SetStateAction<string>>;
  createSessionMutation: MutateLike<{ agentId: string }>;
  createGroupRoomMutation: MutateLike<{ title: string; agentIds: string[]; mode: string; purpose: string }>;
  startGroupRoundMutation: MutateLike<{ roomId: string; topic: string; mode: string; purpose: string }>;
  stopGroupRoundMutation: MutateLike<{ roomId: string }>;
  sendProjectBusMessageMutation: MutateLike<{ content: string; interruptTargets: boolean }>;
  revokeProjectBusMessageMutation: MutateLike<{ eventId: string }>;
  updateGroupRoomMutation: MutateLike<{ roomId: string; title: string; sessionIds: string[]; mode: string; purpose: string }> & {
    isPending: boolean;
  };
  deleteGroupRoomMutation: MutateLike<{ roomId: string }>;
  resetGroupRoomMutation: MutateLike<{ roomId: string }>;
  deleteSessionMutation: MutateLike<{ sessionId: string }>;
  clearSessionHistoryMutation: MutateLike<{ sessionId: string; agentId: string }>;
  addSessionToReviewMutation: MutateLike<{ sessionId: string }>;
  petActionMutation: MutateLike<{ action: PetInteractionAction }>;
  openDeleteSessionConfirm: (session: SessionSummary) => void;
};

export type UseChatWorkspaceActionsResult = {
  handlePetInteraction: (action: PetInteractionAction) => void;
  handleCreateSession: () => void;
  handleOpenProjectAgentBus: () => void;
  handleOpenDirectSession: (sessionId: string) => void;
  handlePrefetchDirectSession: (sessionId: string) => void;
  handleOpenAgent: (agent: AgentInstance) => boolean;
  handleOpenMentionTarget: (target: ChatMentionTarget) => void;
  handleOpenGroupRoom: (roomId: string) => void;
  handleToggleGroupManageSession: (sessionId: string) => void;
  handleToggleGroupComposer: () => void;
  handleToggleGroupAgent: (agentId: string) => void;
  handleCreateGroupRoom: () => void;
  handleStartGroupRound: () => void;
  handleStopGroupRound: () => void;
  handleSendProjectBusMessage: () => void;
  handleRevokeProjectBusMessage: (eventId: string) => void;
  handleApplyGroupRoomManagement: () => void;
  handleDeleteActiveGroupRoom: () => void;
  handleResetActiveGroupRoom: () => void;
  handleDeleteSession: (session: SessionSummary) => void;
  handleClearSessionHistory: (session: SessionSummary) => void;
  handleAddSessionToReview: (session: SessionSummary) => void;
};

/**
 * UI action handlers for session/group workspace navigation and lifecycle.
 * All Chat route writes go through the route controller; this module does not
 * open EventSources and does not build selection URLs itself.
 */
export function useChatWorkspaceActions({
  lang,
  t,
  chatRoute,
  queryClient,
  chatWorkspaceCache,
  setRightIndexPanel,
  setRightPaneCollapsed,
  setSelectedAgentId,
  setSessionFilter,
  setSessionComposerErrors,
  setSessionContextMenu,
  setGroupRoomActionError,
  setGroupComposerOpen,
  setGroupTitleDraft,
  groupTitleDraft,
  groupModeDraft,
  groupPurposeDraft,
  groupSelectedAgentIds,
  setGroupSelectedAgentIds,
  groupTopicDraft,
  projectBusDraft,
  projectBusInterruptTargets,
  setGroupManageSessionIds,
  groupManageTitleDraft,
  groupManageSessionIds,
  groupManageModeDraft,
  groupManagePurposeDraft,
  selectedChatAgentId,
  sessionsById,
  standardGroupRoomActive,
  activeGroupTeamOwned,
  groupRoundActive,
  groupRoundRunning,
  groupManageDisabled,
  groupDeleteDisabled,
  groupResetDisabled,
  activeGroupRoom,
  setPetActionFeedback,
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
  clearSessionHistoryMutation,
  addSessionToReviewMutation,
  petActionMutation,
  openDeleteSessionConfirm,
}: UseChatWorkspaceActionsOptions): UseChatWorkspaceActionsResult {
  const handlePetInteraction = useCallback((action: PetInteractionAction) => {
    setPetActionFeedback("");
    petActionMutation.mutate({ action });
  }, [petActionMutation, setPetActionFeedback]);

  const handleCreateSession = useCallback(() => {
    setRightIndexPanel("conversations");
    setSessionComposerErrors((current) => ({
      ...current,
      __sessions__: "",
    }));
    createSessionMutation.mutate({ agentId: selectedChatAgentId });
  }, [
    createSessionMutation,
    selectedChatAgentId,
    setRightIndexPanel,
    setSessionComposerErrors,
  ]);

  const handleOpenProjectAgentBus = useCallback(() => {
    setSessionContextMenu(null);
    // Explicit project bus route — the URL is the single authority.
    chatRoute.openProjectBus();
    setRightIndexPanel("conversations");
    setRightPaneCollapsed(false);
    setGroupRoomActionError("");
    void chatWorkspaceCache.afterProjectBusFailed();
  }, [
    chatRoute,
    chatWorkspaceCache,
    setGroupRoomActionError,
    setRightIndexPanel,
    setRightPaneCollapsed,
    setSessionContextMenu,
  ]);

  const handlePrefetchDirectSession = useCallback((sessionId: string) => {
    void prefetchSessionDetailWindow(queryClient, sessionId);
  }, [queryClient]);

  const handleOpenDirectSession = useCallback((sessionId: string) => {
    const normalizedSessionId = String(sessionId || "").trim();
    if (!normalizedSessionId) {
      return;
    }
    setSessionContextMenu(null);
    // Temp create shells are local-only — never select/prefetch against the API.
    const tempLocal = isTempSessionId(normalizedSessionId);
    if (!tempLocal) {
      void prefetchSessionDetailWindow(queryClient, normalizedSessionId);
    }
    const sessionAgentId = String(sessionsById?.get(normalizedSessionId)?.agentId || "").trim();
    if (sessionAgentId) {
      setSelectedAgentId(sessionAgentId);
      rememberAgentLastSession(
        sessionAgentId,
        normalizedSessionId,
        chatAgentSessionStorage(),
      );
    }
    setRightIndexPanel("conversations");
    setGroupRoomActionError("");
    setSessionComposerErrors((current) => ({
      ...current,
      [normalizedSessionId]: "",
      __sessions__: "",
    }));
    // replace: true — Codex/ChatGPT thread switch does not push history per tab click.
    chatRoute.openSession(normalizedSessionId);
  }, [
    chatRoute,
    queryClient,
    sessionsById,
    setGroupRoomActionError,
    setRightIndexPanel,
    setSelectedAgentId,
    setSessionComposerErrors,
    setSessionContextMenu,
  ]);

  const handleOpenAgent = useCallback((agent: AgentInstance) => {
    const agentId = String(agent.agentId || "").trim();
    if (!agentId) {
      return false;
    }
    setSelectedAgentId(agentId);
    const knownSessionIds: string[] = [];
    if (sessionsById) {
      for (const session of sessionsById.values()) {
        if (String(session.agentId || "").trim() === agentId) {
          const sessionId = String(session.id || "").trim();
          if (sessionId) {
            knownSessionIds.push(sessionId);
          }
        }
      }
    }
    const targetSessionId = resolveAgentOpenSessionId({
      lastSessionId: lastSessionForAgent(
        agentId,
        readAgentLastSessionMap(chatAgentSessionStorage()),
      ),
      knownSessionIds,
      latestSessionId: "",
      directSessionId: agent.directSessionId,
    });
    if (!targetSessionId) {
      return false;
    }
    handleOpenDirectSession(targetSessionId);
    return true;
  }, [handleOpenDirectSession, sessionsById, setSelectedAgentId]);

  const handleOpenMentionTarget = useCallback((target: ChatMentionTarget) => {
    setRightPaneCollapsed(false);
    setGroupRoomActionError("");
    if (target.kind === "all") {
      chatRoute.openProjectBus();
      setRightIndexPanel("conversations");
      setSessionFilter("");
      void chatWorkspaceCache.afterProjectBusFailed();
      return;
    }
    if (target.directSessionId) {
      setSessionFilter("");
      handleOpenDirectSession(target.directSessionId);
      return;
    }
    const fallbackFilter = target.agentCode || target.displayName || target.agentId || "";
    if (fallbackFilter) {
      setRightIndexPanel("conversations");
      setSessionFilter(fallbackFilter);
    }
  }, [
    chatRoute,
    chatWorkspaceCache,
    handleOpenDirectSession,
    setGroupRoomActionError,
    setRightIndexPanel,
    setRightPaneCollapsed,
    setSessionFilter,
  ]);

  const handleOpenGroupRoom = useCallback((roomId: string) => {
    if (!roomId) {
      return;
    }
    // Group room entry pushes history (product semantics).
    chatRoute.openRoom(roomId);
    setRightIndexPanel("members");
    setRightPaneCollapsed(false);
    setGroupRoomActionError("");
    void chatWorkspaceCache.afterChatRoomChanged(roomId);
  }, [
    chatRoute,
    chatWorkspaceCache,
    setGroupRoomActionError,
    setRightIndexPanel,
    setRightPaneCollapsed,
  ]);

  const handleToggleGroupManageSession = useCallback((sessionId: string) => {
    if (!sessionId || activeGroupTeamOwned || groupRoundActive || updateGroupRoomMutation.isPending) {
      return;
    }
    setGroupRoomActionError("");
    setGroupManageSessionIds((current) =>
      current.includes(sessionId)
        ? current.filter((item) => item !== sessionId)
        : [...current, sessionId],
    );
  }, [
    activeGroupTeamOwned,
    groupRoundActive,
    setGroupManageSessionIds,
    setGroupRoomActionError,
    updateGroupRoomMutation.isPending,
  ]);

  const handleToggleGroupComposer = useCallback(() => {
    setSessionComposerErrors((current) => ({
      ...current,
      __sessions__: "",
    }));
    setGroupComposerOpen((open) => {
      const nextOpen = !open;
      if (nextOpen && !groupTitleDraft.trim()) {
        setGroupTitleDraft(lang === "zh" ? "Agent 群聊" : "Agent group");
      }
      return nextOpen;
    });
  }, [groupTitleDraft, lang, setGroupComposerOpen, setGroupTitleDraft, setSessionComposerErrors]);

  const handleToggleGroupAgent = useCallback((agentId: string) => {
    setSessionComposerErrors((current) => ({
      ...current,
      __sessions__: "",
    }));
    setGroupSelectedAgentIds((current) =>
      current.includes(agentId) ? current.filter((item) => item !== agentId) : [...current, agentId],
    );
  }, [setGroupSelectedAgentIds, setSessionComposerErrors]);

  const handleCreateGroupRoom = useCallback(() => {
    const title = groupTitleDraft.trim();
    const agentIds = groupSelectedAgentIds.filter(Boolean);
    if (!title || agentIds.length < 2 || createGroupRoomMutation.isPending) {
      setSessionComposerErrors((current) => ({
        ...current,
        __sessions__: lang === "zh" ? "请输入群聊名称，并至少选择两个 Agent。" : "Enter a group name and choose at least two agents.",
      }));
      return;
    }
    createGroupRoomMutation.mutate({
      title,
      agentIds,
      mode: groupModeDraft || "round_robin",
      purpose: groupPurposeDraft || "discussion",
    });
  }, [
    createGroupRoomMutation,
    groupModeDraft,
    groupPurposeDraft,
    groupSelectedAgentIds,
    groupTitleDraft,
    lang,
    setSessionComposerErrors,
  ]);

  const handleStartGroupRound = useCallback(() => {
    const topic = groupTopicDraft.trim();
    if (!standardGroupRoomActive || !activeGroupRoom?.roomId || !topic || startGroupRoundMutation.isPending || groupRoundActive) {
      return;
    }
    startGroupRoundMutation.mutate({
      roomId: activeGroupRoom.roomId,
      topic,
      mode: activeGroupRoom?.mode || "round_robin",
      purpose: activeGroupRoom?.purpose || "discussion",
    });
  }, [
    activeGroupRoom?.mode,
    activeGroupRoom?.purpose,
    activeGroupRoom?.roomId,
    groupRoundActive,
    groupTopicDraft,
    standardGroupRoomActive,
    startGroupRoundMutation,
  ]);

  const handleStopGroupRound = useCallback(() => {
    if (!standardGroupRoomActive || !activeGroupRoom?.roomId || !groupRoundRunning || stopGroupRoundMutation.isPending) {
      return;
    }
    stopGroupRoundMutation.mutate({
      roomId: activeGroupRoom.roomId,
    });
  }, [
    activeGroupRoom?.roomId,
    groupRoundRunning,
    standardGroupRoomActive,
    stopGroupRoundMutation,
  ]);

  const handleSendProjectBusMessage = useCallback(() => {
    const content = projectBusDraft.trim();
    if (!content || sendProjectBusMessageMutation.isPending) {
      return;
    }
    sendProjectBusMessageMutation.mutate({
      content,
      interruptTargets: projectBusInterruptTargets,
    });
  }, [projectBusDraft, projectBusInterruptTargets, sendProjectBusMessageMutation]);

  const handleRevokeProjectBusMessage = useCallback((eventId: string) => {
    if (!eventId || revokeProjectBusMessageMutation.isPending) {
      return;
    }
    revokeProjectBusMessageMutation.mutate({ eventId });
  }, [revokeProjectBusMessageMutation]);

  const handleApplyGroupRoomManagement = useCallback(() => {
    if (!standardGroupRoomActive || activeGroupTeamOwned || !activeGroupRoom?.roomId || groupManageDisabled) {
      return;
    }
    updateGroupRoomMutation.mutate({
      roomId: activeGroupRoom.roomId,
      title: groupManageTitleDraft.trim(),
      sessionIds: groupManageSessionIds,
      mode: groupManageModeDraft || "round_robin",
      purpose: groupManagePurposeDraft || "discussion",
    });
  }, [
    activeGroupRoom?.roomId,
    activeGroupTeamOwned,
    groupManageDisabled,
    groupManageModeDraft,
    groupManagePurposeDraft,
    groupManageSessionIds,
    groupManageTitleDraft,
    standardGroupRoomActive,
    updateGroupRoomMutation,
  ]);

  const handleDeleteActiveGroupRoom = useCallback(() => {
    if (!standardGroupRoomActive || activeGroupTeamOwned || !activeGroupRoom?.roomId || groupDeleteDisabled) {
      return;
    }
    const roomTitle = (activeGroupRoom?.title || activeGroupRoom.roomId).trim();
    const groupConfirmMessage = t("deleteGroupConfirm").replace("{title}", roomTitle || activeGroupRoom.roomId);
    if (!window.confirm(groupConfirmMessage)) {
      return;
    }
    deleteGroupRoomMutation.mutate({ roomId: activeGroupRoom.roomId });
  }, [
    activeGroupRoom?.roomId,
    activeGroupRoom?.title,
    activeGroupTeamOwned,
    deleteGroupRoomMutation,
    groupDeleteDisabled,
    standardGroupRoomActive,
    t,
  ]);

  const handleResetActiveGroupRoom = useCallback(() => {
    if (!standardGroupRoomActive || !activeGroupRoom?.roomId || groupResetDisabled) {
      return;
    }
    const roomTitle = (activeGroupRoom?.title || activeGroupRoom.roomId).trim();
    const groupConfirmMessage = t("resetGroupConfirm").replace("{title}", roomTitle || activeGroupRoom.roomId);
    if (!window.confirm(groupConfirmMessage)) {
      return;
    }
    resetGroupRoomMutation.mutate({ roomId: activeGroupRoom.roomId });
  }, [
    activeGroupRoom?.roomId,
    activeGroupRoom?.title,
    groupResetDisabled,
    resetGroupRoomMutation,
    standardGroupRoomActive,
    t,
  ]);

  const handleDeleteSession = useCallback((session: SessionSummary) => {
    setSessionContextMenu(null);
    const alreadyDeletingThisSession = Boolean(
      deleteSessionMutation.isPending
      && deleteSessionMutation.variables?.sessionId === session.id,
    );
    if (alreadyDeletingThisSession || isBusyPhase(session.currentPhase || session.status)) {
      setSessionComposerErrors((current) => ({
        ...current,
        [session.id]: t("deleteSessionBusy"),
        __sessions__: "",
      }));
      return;
    }
    openDeleteSessionConfirm(session);
  }, [deleteSessionMutation, openDeleteSessionConfirm, setSessionComposerErrors, setSessionContextMenu, t]);

  const handleClearSessionHistory = useCallback((session: SessionSummary) => {
    setSessionContextMenu(null);
    if (!session.agentId || !isAgentRootSession(session)) {
      return;
    }
    if (isBusyPhase(session.currentPhase || session.status)) {
      setSessionComposerErrors((current) => ({
        ...current,
        [session.id]: t("clearSessionHistoryBusy"),
        __sessions__: "",
      }));
      return;
    }
    const sessionTitle = (session.agentDisplayName || session.title || session.id).trim();
    const confirmMessage = t("clearSessionHistoryConfirm").replace("{title}", sessionTitle || session.id);
    if (!window.confirm(confirmMessage)) {
      return;
    }
    setSessionComposerErrors((current) => ({
      ...current,
      [session.id]: "",
      __sessions__: "",
    }));
    clearSessionHistoryMutation.mutate({ sessionId: session.id, agentId: session.agentId });
  }, [clearSessionHistoryMutation, setSessionComposerErrors, setSessionContextMenu, t]);

  const handleAddSessionToReview = useCallback((session: SessionSummary) => {
    setSessionContextMenu(null);
    if (isBusyPhase(session.currentPhase || session.status)) {
      setSessionComposerErrors((current) => ({
        ...current,
        [session.id]: t("addSessionToReviewBusy"),
        __sessions__: "",
      }));
      return;
    }
    setSessionComposerErrors((current) => ({
      ...current,
      [session.id]: "",
      __sessions__: "",
    }));
    addSessionToReviewMutation.mutate({ sessionId: session.id });
  }, [addSessionToReviewMutation, setSessionComposerErrors, setSessionContextMenu, t]);

  return {
    handlePetInteraction,
    handleCreateSession,
    handleOpenProjectAgentBus,
    handleOpenDirectSession,
    handlePrefetchDirectSession,
    handleOpenAgent,
    handleOpenMentionTarget,
    handleOpenGroupRoom,
    handleToggleGroupManageSession,
    handleToggleGroupComposer,
    handleToggleGroupAgent,
    handleCreateGroupRoom,
    handleStartGroupRound,
    handleStopGroupRound,
    handleSendProjectBusMessage,
    handleRevokeProjectBusMessage,
    handleApplyGroupRoomManagement,
    handleDeleteActiveGroupRoom,
    handleResetActiveGroupRoom,
    handleDeleteSession,
    handleClearSessionHistory,
    handleAddSessionToReview,
  };
}
