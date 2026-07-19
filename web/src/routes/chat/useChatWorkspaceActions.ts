import { useCallback, type Dispatch, type MutableRefObject, type SetStateAction } from "react";
import type { NavigateFunction } from "react-router-dom";

import type {
  AgentInstance,
  ChatRoomDetail,
  SessionSummary,
} from "../../api/types";
import type { TranslationKey } from "../../i18n/dictionary";
import { isAgentRootSession } from "../DirectSessionIndexItem";
import type { ChatMentionTarget } from "../chatMentionTokens";
import type { createChatWorkspaceCache } from "../chatWorkspaceCache";
import { isBusyPhase } from "./chatCodingRouteViewModel";

type ChatWorkspaceCache = ReturnType<typeof createChatWorkspaceCache>;
type RightIndexPanel = "conversations" | "members";
type PetInteractionAction = "feed" | "talk" | "care";

type MutateLike<TVariables> = {
  mutate: (variables: TVariables) => void;
  isPending: boolean;
};

export type UseChatWorkspaceActionsOptions = {
  lang: "zh" | "en";
  t: (key: TranslationKey) => string;
  navigate: NavigateFunction;
  chatWorkspaceCache: ChatWorkspaceCache;
  latestDirectSessionSelectionRef: MutableRefObject<string>;
  setActiveSession: (sessionId: string) => void;
  activeGroupRoomId: string;
  setActiveGroupRoomId: Dispatch<SetStateAction<string>>;
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
  selectDirectSessionMutation: MutateLike<string>;
  petActionMutation: MutateLike<{ action: PetInteractionAction }>;
};

export type UseChatWorkspaceActionsResult = {
  handlePetInteraction: (action: PetInteractionAction) => void;
  handleCreateSession: () => void;
  handleOpenProjectAgentBus: () => void;
  handleOpenDirectSession: (sessionId: string) => void;
  handleOpenAgent: (agent: AgentInstance) => void;
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
 * Mutations are injected; this module does not open EventSources.
 */
export function useChatWorkspaceActions({
  lang,
  t,
  navigate,
  chatWorkspaceCache,
  latestDirectSessionSelectionRef,
  setActiveSession,
  activeGroupRoomId,
  setActiveGroupRoomId,
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
  selectDirectSessionMutation,
  petActionMutation,
}: UseChatWorkspaceActionsOptions): UseChatWorkspaceActionsResult {
  const handlePetInteraction = useCallback((action: PetInteractionAction) => {
    setPetActionFeedback("");
    petActionMutation.mutate({ action });
  }, [petActionMutation, setPetActionFeedback]);

  const handleCreateSession = useCallback(() => {
    setActiveGroupRoomId("");
    setRightIndexPanel("conversations");
    setSessionComposerErrors((current) => ({
      ...current,
      __sessions__: "",
    }));
    createSessionMutation.mutate({ agentId: selectedChatAgentId });
  }, [
    createSessionMutation,
    selectedChatAgentId,
    setActiveGroupRoomId,
    setRightIndexPanel,
    setSessionComposerErrors,
  ]);

  const handleOpenProjectAgentBus = useCallback(() => {
    setSessionContextMenu(null);
    navigate("/chat", { replace: false });
    setActiveGroupRoomId("__project_agent_bus__");
    setRightIndexPanel("conversations");
    setRightPaneCollapsed(false);
    setGroupRoomActionError("");
    void chatWorkspaceCache.afterProjectBusFailed();
  }, [
    chatWorkspaceCache,
    navigate,
    setActiveGroupRoomId,
    setGroupRoomActionError,
    setRightIndexPanel,
    setRightPaneCollapsed,
    setSessionContextMenu,
  ]);

  const handleOpenDirectSession = useCallback((sessionId: string) => {
    const normalizedSessionId = String(sessionId || "").trim();
    if (!normalizedSessionId) {
      return;
    }
    setSessionContextMenu(null);
    latestDirectSessionSelectionRef.current = normalizedSessionId;
    setActiveSession(normalizedSessionId);
    setActiveGroupRoomId("");
    setRightIndexPanel("conversations");
    setGroupRoomActionError("");
    setSessionComposerErrors((current) => ({
      ...current,
      [normalizedSessionId]: "",
      __sessions__: "",
    }));
    selectDirectSessionMutation.mutate(normalizedSessionId);
    navigate(`/chat?session=${encodeURIComponent(normalizedSessionId)}`, { replace: false });
  }, [
    latestDirectSessionSelectionRef,
    navigate,
    selectDirectSessionMutation,
    setActiveGroupRoomId,
    setActiveSession,
    setGroupRoomActionError,
    setRightIndexPanel,
    setSessionComposerErrors,
    setSessionContextMenu,
  ]);

  const handleOpenAgent = useCallback((agent: AgentInstance) => {
    const agentId = String(agent.agentId || "").trim();
    const primarySessionId = String(agent.directSessionId || "").trim();
    if (!agentId || !primarySessionId) {
      return;
    }
    setSelectedAgentId(agentId);
    handleOpenDirectSession(primarySessionId);
  }, [handleOpenDirectSession, setSelectedAgentId]);

  const handleOpenMentionTarget = useCallback((target: ChatMentionTarget) => {
    setRightPaneCollapsed(false);
    setGroupRoomActionError("");
    if (target.kind === "all") {
      setActiveGroupRoomId("__project_agent_bus__");
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
      setActiveGroupRoomId("");
      setRightIndexPanel("conversations");
      setSessionFilter(fallbackFilter);
    }
  }, [
    chatWorkspaceCache,
    handleOpenDirectSession,
    setActiveGroupRoomId,
    setGroupRoomActionError,
    setRightIndexPanel,
    setRightPaneCollapsed,
    setSessionFilter,
  ]);

  const handleOpenGroupRoom = useCallback((roomId: string) => {
    if (!roomId) {
      return;
    }
    navigate(`/chat?room=${encodeURIComponent(roomId)}`, { replace: false });
    setActiveGroupRoomId(roomId);
    setRightIndexPanel("members");
    setRightPaneCollapsed(false);
    setGroupRoomActionError("");
    void chatWorkspaceCache.afterChatRoomChanged(roomId);
  }, [
    chatWorkspaceCache,
    navigate,
    setActiveGroupRoomId,
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
    if (!standardGroupRoomActive || !activeGroupRoomId || !topic || startGroupRoundMutation.isPending || groupRoundActive) {
      return;
    }
    startGroupRoundMutation.mutate({
      roomId: activeGroupRoomId,
      topic,
      mode: activeGroupRoom?.mode || "round_robin",
      purpose: activeGroupRoom?.purpose || "discussion",
    });
  }, [
    activeGroupRoom?.mode,
    activeGroupRoom?.purpose,
    activeGroupRoomId,
    groupRoundActive,
    groupTopicDraft,
    standardGroupRoomActive,
    startGroupRoundMutation,
  ]);

  const handleStopGroupRound = useCallback(() => {
    if (!standardGroupRoomActive || !activeGroupRoomId || !groupRoundRunning || stopGroupRoundMutation.isPending) {
      return;
    }
    stopGroupRoundMutation.mutate({
      roomId: activeGroupRoomId,
    });
  }, [
    activeGroupRoomId,
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
    if (!standardGroupRoomActive || activeGroupTeamOwned || !activeGroupRoomId || groupManageDisabled) {
      return;
    }
    updateGroupRoomMutation.mutate({
      roomId: activeGroupRoomId,
      title: groupManageTitleDraft.trim(),
      sessionIds: groupManageSessionIds,
      mode: groupManageModeDraft || "round_robin",
      purpose: groupManagePurposeDraft || "discussion",
    });
  }, [
    activeGroupRoomId,
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
    if (!standardGroupRoomActive || activeGroupTeamOwned || !activeGroupRoomId || groupDeleteDisabled) {
      return;
    }
    const roomTitle = (activeGroupRoom?.title || activeGroupRoomId).trim();
    const groupConfirmMessage = t("deleteGroupConfirm").replace("{title}", roomTitle || activeGroupRoomId);
    if (!window.confirm(groupConfirmMessage)) {
      return;
    }
    deleteGroupRoomMutation.mutate({ roomId: activeGroupRoomId });
  }, [
    activeGroupRoom?.title,
    activeGroupRoomId,
    activeGroupTeamOwned,
    deleteGroupRoomMutation,
    groupDeleteDisabled,
    standardGroupRoomActive,
    t,
  ]);

  const handleResetActiveGroupRoom = useCallback(() => {
    if (!standardGroupRoomActive || !activeGroupRoomId || groupResetDisabled) {
      return;
    }
    const roomTitle = (activeGroupRoom?.title || activeGroupRoomId).trim();
    const groupConfirmMessage = t("resetGroupConfirm").replace("{title}", roomTitle || activeGroupRoomId);
    if (!window.confirm(groupConfirmMessage)) {
      return;
    }
    resetGroupRoomMutation.mutate({ roomId: activeGroupRoomId });
  }, [
    activeGroupRoom?.title,
    activeGroupRoomId,
    groupResetDisabled,
    resetGroupRoomMutation,
    standardGroupRoomActive,
    t,
  ]);

  const handleDeleteSession = useCallback((session: SessionSummary) => {
    setSessionContextMenu(null);
    if (isBusyPhase(session.currentPhase || session.status)) {
      setSessionComposerErrors((current) => ({
        ...current,
        [session.id]: t("deleteSessionBusy"),
        __sessions__: "",
      }));
      return;
    }
    const sessionTitle = (session.agentDisplayName || session.title || session.id).trim();
    const sessionConfirmMessage = t("deleteSessionConfirm").replace("{title}", sessionTitle || session.id);
    if (!window.confirm(sessionConfirmMessage)) {
      return;
    }
    setSessionComposerErrors((current) => ({
      ...current,
      [session.id]: "",
      __sessions__: "",
    }));
    deleteSessionMutation.mutate({ sessionId: session.id });
  }, [deleteSessionMutation, setSessionComposerErrors, setSessionContextMenu, t]);

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
