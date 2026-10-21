import { useMemo, type ComponentProps } from "react";
import type { NavigateFunction } from "react-router-dom";

import type {
  AgentInstance,
  AgentPermissionPreset,
  RuntimeSummary,
  SessionDetail,
  SessionGuidanceMode,
  SessionSummary,
  SkillLibraryItem,
} from "../../api/types";
import type {
  ConversationLlmControl,
  ConversationTurnModelControl,
  ConversationViewProps,
} from "../../components/conversation/conversationViewTypes";
import type { TranslationKey } from "../../i18n/dictionary";
import { resolveChatUserDisplayName } from "../chatCompactPanel";
import { teamWorkspaceRoute } from "../teams/researchWorkspaceModel";
import {
  ChatComposerPlusMenu,
  type ChatComposerKnowledgeReferenceState,
  type ChatComposerSessionReferenceOption,
} from "./ChatComposerPlusMenu";
import type { ChatComposerBudgetControl } from "./ChatComposerBudgetPopover";
import type {
  ChatConversationComposerBridge,
  ChatConversationComposerBridgeState,
} from "./ChatConversationComposerBridge";
import type { ComposerContextRingModel } from "./composerContextModel";
import type { UpdateAgentPermissionPresetInput } from "./useAgentPermissionPresetMutation";

const EMPTY_SESSION_CHANGED_FILES: string[] = [];

type ConversationBridgeProps = Omit<ComponentProps<typeof ChatConversationComposerBridge>, "fallback">;

type ChatConversationTranscriptKey =
  | "title"
  | "phase"
  | "sessionWorkspacePath"
  | "transcriptPending"
  | "hasEarlierMessages"
  | "earlierMessagesLoading"
  | "onStreamingFramePaint"
  | "showHeader"
  | "showSessionOverview"
  | "showMentalSnapshots"
  | "showComposer"
  | "companionMode"
  | "autoScrollToLatest"
  | "turnError"
  | "onLoadEarlierMessages";

type ChatConversationParticipantsKey =
  | "assistantDisplayName"
  | "assistantAvatarImageUrl"
  | "assistantAvatarFallback"
  | "resolveTurnAvatar"
  | "userDisplayName"
  | "userAvatarPreset"
  | "userAvatarImageUrl"
  | "taskSummary"
  | "changedFiles"
  | "defaultFileContext";

type ChatConversationComposerChromeKey =
  | "promptSuggestionEnabled"
  | "composerFocusSignal"
  | "onComposerFocusRequestSettled"
  | "composer"
  | "composerLeadingControl"
  | "permissionControl"
  | "llmControl"
  | "turnModelControl"
  | "onOpenAgentModelConfig"
  | "composerContextRing"
  | "onOpenComposerContextDetail"
  | "onCreateSession"
  | "onOpenSideChat"
  | "onOpenRailFile"
  | "slashCommandSuggestions"
  | "slashSkillsCatalogState"
  | "composerReferenceOptions"
  | "cancelComposerModeLabel"
  | "stopLabel"
  | "stopPendingLabel"
  | "safeGuidanceLabel"
  | "safeGuidancePendingLabel"
  | "interruptGuidanceLabel"
  | "interruptGuidancePendingLabel"
  | "onComposerChange"
  | "onAddComposerAttachments"
  | "onRemoveComposerAttachment"
  | "onRetryComposerAttachment"
  | "onRetryComposerAttachmentUploads"
  | "onAddComposerReference"
  | "onRemoveComposerReference"
  | "onSubmit"
  | "onStop"
  | "onSafeGuidance"
  | "onInterruptGuidance";

type ChatConversationTurnActionsKey =
  | "editUserMessageLabel"
  | "onEditUserMessage"
  | "onRegenerateAssistantMessage"
  | "onSwitchMessageVersion"
  | "onForkSessionFromNode"
  | "branchVersionSwitchDisabled"
  | "regenerableAssistantMessageId"
  | "regenerateDisabled"
  | "regeneratePending"
  | "onRetryTurn"
  | "retryTurnDisabled"
  | "retryTurnPending"
  | "onCancelComposerMode"
  | "onFollowupQueueUpdate"
  | "onFollowupQueueRemove"
  | "onFollowupQueueMove"
  | "onFollowupQueueSteer"
  | "onFollowupQueueSendNow"
  | "followupQueueSteerLabel";

export type ChatConversationTranscriptModel = Pick<ConversationBridgeProps, ChatConversationTranscriptKey>;
export type ChatConversationParticipantsModel = Pick<ConversationBridgeProps, ChatConversationParticipantsKey>;
export type ChatConversationComposerChromeModel = Pick<ConversationBridgeProps, ChatConversationComposerChromeKey>;
export type ChatConversationTurnActionsModel = Pick<ConversationBridgeProps, ChatConversationTurnActionsKey>;

/** Flat bridge props grouped so the workspace panel does not take the whole composer surface at once. */
export type ChatConversationSurfaceModel = {
  sessionId: string;
  messages: ConversationBridgeProps["messages"];
  transcript: ChatConversationTranscriptModel;
  participants: ChatConversationParticipantsModel;
  composerChrome: ChatConversationComposerChromeModel;
  turnActions: ChatConversationTurnActionsModel;
};

export type ChatConversationSurfaceModelInput = {
  activeAgentAvatarFallback: string;
  activeAgentAvatarImageUrl: string | undefined;
  activeAgentDisplayName: string;
  activeGroupRoom: { title: string } | null | undefined;
  activeGroupTeam: { teamId: string } | null | undefined;
  activeGroupTeamOwned: boolean;
  activePromptSuggestionEnabled: boolean;
  activeSessionAgent: AgentInstance | null | undefined;
  activeSessionId: string | null;
  agentDirectSessionMismatch: boolean;
  agentPermissionPresetMutation: {
    isPending: boolean;
    variables?: { agentId?: string } | undefined;
    mutate: (input: UpdateAgentPermissionPresetInput) => void;
  };
  agentPrimaryDirectSessionId: string;
  cacheDetailAvailable: boolean;
  companionConversationComposer: ChatConversationComposerBridgeState;
  composerBudgetControl: ChatComposerBudgetControl | undefined;
  composerContextRing: ComposerContextRingModel | null;
  composerFocusRequest: { sessionId: string; signal: string };
  composerKnowledgeReferenceOptions: ChatComposerSessionReferenceOption[];
  knowledgeReferenceState?: ChatComposerKnowledgeReferenceState;
  composerSessionReferenceOptions: ChatComposerSessionReferenceOption[];
  currentTaskSummary: string;
  detail: SessionDetail | null | undefined;
  financeSurface: boolean;
  handleAddComposerAttachments: NonNullable<ConversationViewProps["onAddComposerAttachments"]>;
  handleAddComposerReference: NonNullable<ConversationViewProps["onAddComposerReference"]>;
  handleCancelEditMessage: () => void;
  handleComposerChange: ConversationViewProps["onComposerChange"];
  handleConversationStreamingFramePaint: NonNullable<ConversationViewProps["onStreamingFramePaint"]>;
  handleCreateAgentSession: (agent: AgentInstance) => void;
  handleEditUserMessage: NonNullable<ConversationViewProps["onEditUserMessage"]>;
  handleFollowupQueueMove: NonNullable<ConversationViewProps["onFollowupQueueMove"]>;
  handleFollowupQueueRemove: NonNullable<ConversationViewProps["onFollowupQueueRemove"]>;
  handleFollowupQueueSendNow: NonNullable<ConversationViewProps["onFollowupQueueSendNow"]>;
  handleFollowupQueueSteer: NonNullable<ConversationViewProps["onFollowupQueueSteer"]>;
  handleFollowupQueueUpdate: NonNullable<ConversationViewProps["onFollowupQueueUpdate"]>;
  handleForkSessionFromNode: NonNullable<ConversationViewProps["onForkSessionFromNode"]>;
  handleLoadEarlierSessionMessages: () => void;
  handleMentalModelEnabledChange: (enabled: boolean) => void;
  handleOpenAgentConfig: (agent: AgentInstance, latestSession: SessionSummary | null) => void;
  handleOpenDirectSession: (sessionId: string, options?: { telemetrySource?: string }) => void;
  handlePrefetchDirectSession: (sessionId: string) => void;
  handlePromptSuggestionEnabledChange: (enabled: boolean) => void;
  handleRegenerateAssistantMessage: NonNullable<ConversationViewProps["onRegenerateAssistantMessage"]>;
  handleRemoveComposerAttachment: NonNullable<ConversationViewProps["onRemoveComposerAttachment"]>;
  handleRemoveComposerReference: NonNullable<ConversationViewProps["onRemoveComposerReference"]>;
  handleRetryComposerAttachmentUpload: NonNullable<ConversationViewProps["onRetryComposerAttachment"]>;
  handleRetryComposerAttachmentUploads: NonNullable<ConversationViewProps["onRetryComposerAttachmentUploads"]>;
  handleRetryFailedTurn: () => void;
  handleRuntimeStatusEnabledChange: (enabled: boolean) => void;
  handleStopTurn: () => void;
  handleSubmitGuidance: (mode: SessionGuidanceMode) => void;
  handleSubmitTurn: () => void;
  handleSwitchMessageVersion: NonNullable<ConversationViewProps["onSwitchMessageVersion"]>;
  lang: "zh" | "en";
  loadEarlierSessionMessagesMutation: { isPending: boolean };
  mentalModelEnabledForNextTurn: boolean;
  navigate: NavigateFunction;
  openCacheDetail: () => void;
  openOrdinaryRailFile: (path: string) => void;
  openOrdinarySideChat: (draft: string, sendDraft: boolean) => void;
  ordinaryChangeRail: boolean;
  regenerateMutation: {
    isPending: boolean;
    variables?: { sessionId?: string } | undefined;
  };
  regenerableAssistantMessageId: string;
  resolveConversationTurnAvatar: NonNullable<ConversationViewProps["resolveTurnAvatar"]>;
  resolvedEditTarget: { messageId: string; original: string } | null;
  runtime: Pick<RuntimeSummary, "userName" | "userProfile"> | null | undefined;
  runtimeStatusEnabledForNextTurn: boolean;
  selectedChatAgent: AgentInstance | undefined;
  sessionBindingMismatchLine: string;
  sessionBusy: boolean;
  modelParametersSavePending: boolean;
  sessionTranscriptPending: boolean;
  sessionsById: ReadonlyMap<string, SessionSummary>;
  setGroupManageDialogOpen: (open: boolean) => void;
  settleSessionComposerFocusRequest: (focusSignal: string) => void;
  slashCommandSuggestions: SkillLibraryItem[];
  slashSkillsCatalogState: "ready" | "loading" | "error";
  standardGroupRoomActive: boolean;
  switchHeadMutation: {
    isPending: boolean;
    variables?: { sessionId?: string } | undefined;
  };
  t: (key: TranslationKey) => string;
  turnModelControl: ConversationTurnModelControl | undefined;
  verifiedCompanionMode: boolean;
};

export function useChatConversationSurfaceModel({
  activeAgentAvatarFallback,
  activeAgentAvatarImageUrl,
  activeAgentDisplayName,
  activeGroupRoom,
  activeGroupTeam,
  activeGroupTeamOwned,
  activePromptSuggestionEnabled,
  activeSessionAgent,
  activeSessionId,
  agentDirectSessionMismatch,
  agentPermissionPresetMutation,
  agentPrimaryDirectSessionId,
  cacheDetailAvailable,
  companionConversationComposer,
  composerBudgetControl,
  composerContextRing,
  composerFocusRequest,
  composerKnowledgeReferenceOptions,
  knowledgeReferenceState,
  composerSessionReferenceOptions,
  currentTaskSummary,
  detail,
  financeSurface,
  handleAddComposerAttachments,
  handleAddComposerReference,
  handleCancelEditMessage,
  handleComposerChange,
  handleConversationStreamingFramePaint,
  handleCreateAgentSession,
  handleEditUserMessage,
  handleFollowupQueueMove,
  handleFollowupQueueRemove,
  handleFollowupQueueSendNow,
  handleFollowupQueueSteer,
  handleFollowupQueueUpdate,
  handleForkSessionFromNode,
  handleLoadEarlierSessionMessages,
  handleMentalModelEnabledChange,
  handleOpenAgentConfig,
  handleOpenDirectSession,
  handlePrefetchDirectSession,
  handlePromptSuggestionEnabledChange,
  handleRegenerateAssistantMessage,
  handleRemoveComposerAttachment,
  handleRemoveComposerReference,
  handleRetryComposerAttachmentUpload,
  handleRetryComposerAttachmentUploads,
  handleRetryFailedTurn,
  handleRuntimeStatusEnabledChange,
  handleStopTurn,
  handleSubmitGuidance,
  handleSubmitTurn,
  handleSwitchMessageVersion,
  lang,
  loadEarlierSessionMessagesMutation,
  mentalModelEnabledForNextTurn,
  navigate,
  openCacheDetail,
  openOrdinaryRailFile,
  openOrdinarySideChat,
  ordinaryChangeRail,
  regenerateMutation,
  regenerableAssistantMessageId,
  resolveConversationTurnAvatar,
  resolvedEditTarget,
  runtime,
  runtimeStatusEnabledForNextTurn,
  selectedChatAgent,
  sessionBindingMismatchLine,
  sessionBusy,
  modelParametersSavePending,
  sessionTranscriptPending,
  sessionsById,
  setGroupManageDialogOpen,
  settleSessionComposerFocusRequest,
  slashCommandSuggestions,
  slashSkillsCatalogState,
  standardGroupRoomActive,
  switchHeadMutation,
  t,
  turnModelControl,
  verifiedCompanionMode
}: ChatConversationSurfaceModelInput): ChatConversationSurfaceModel | null {
  // Conversation surface model, memoized so unrelated workbench renders (rails,
  // dialogs, composer state) do not re-render ConversationView: the memo gate
  // lives on ConversationView and needs stable prop references. The streaming
  // activeTurnMessage is intentionally NOT part of this model — it is
  // projected from the active-turn layer store inside
  // ChatConversationComposerBridge, the single per-frame subscriber.
  const conversationModel = useMemo(
    () => (detail ? {
      sessionId: activeSessionId ?? detail.id,
      title: detail.title,
      phase: detail.currentPhase,
      // Session summary carries an absolute workspace root (backend resolves
      // relative paths against PROJECT_ROOT); markdown workspace-file links
      // resolve against it. Undefined keeps links inert (legacy behavior).
      sessionWorkspacePath: detail.workspaceRoot || detail.workspacePath,
      messages: detail.messages,
      transcriptPending: sessionTranscriptPending,
      hasEarlierMessages: Boolean(detail.messageWindow?.hasEarlier),
      earlierMessagesLoading: loadEarlierSessionMessagesMutation.isPending,
      onStreamingFramePaint: handleConversationStreamingFramePaint,
      assistantDisplayName: activeAgentDisplayName,
      assistantAvatarImageUrl: activeAgentAvatarImageUrl,
      assistantAvatarFallback: activeAgentAvatarFallback,
      resolveTurnAvatar: resolveConversationTurnAvatar,
      userDisplayName: resolveChatUserDisplayName(runtime?.userName),
      userAvatarPreset: runtime?.userProfile?.avatarPreset,
      userAvatarImageUrl: runtime?.userProfile?.avatarImageUrl,
      taskSummary: currentTaskSummary,
      changedFiles: detail.changedFiles ?? EMPTY_SESSION_CHANGED_FILES,
      defaultFileContext: detail.defaultFileContext,
      showHeader: false,
      showSessionOverview: false,
      companionMode: verifiedCompanionMode,
      // Historical mental snapshots are conversation evidence; next-turn toggle only affects submit.
      showMentalSnapshots: !verifiedCompanionMode,
      promptSuggestionEnabled: !verifiedCompanionMode && activePromptSuggestionEnabled,
      composerFocusSignal:
        composerFocusRequest.sessionId === activeSessionId
          ? composerFocusRequest.signal
          : "",
      onComposerFocusRequestSettled: settleSessionComposerFocusRequest,
      composer: financeSurface ? { ...companionConversationComposer, placeholder: lang === "zh" ? "追问这只股票…" : "Ask about this stock…" } : verifiedCompanionMode ? { ...companionConversationComposer, placeholder: lang === "zh" ? "发送消息…" : "Send a message…" } : companionConversationComposer,
      composerLeadingControl: verifiedCompanionMode ? undefined : (
        <ChatComposerPlusMenu
          lang={lang}
          attachmentDisabled={companionConversationComposer.attachmentInputDisabled}
          onAddAttachments={handleAddComposerAttachments}
          sessionReferences={composerSessionReferenceOptions}
          onAddSessionReference={handleAddComposerReference}
          knowledgeReferenceOptions={composerKnowledgeReferenceOptions}
          knowledgeReferenceState={knowledgeReferenceState}
          onAddKnowledgeReference={handleAddComposerReference}
          labels={{
            composerAttachFiles: t("composerAttachFiles"),
            composerReferenceKnowledgeFiles: t("composerReferenceKnowledgeFiles"),
            composerReferenceKnowledgeUnavailable: t("composerReferenceKnowledgeUnavailable"),
            composerReferenceKnowledgeTitle: t("composerReferenceKnowledgeTitle"),
            composerReferenceKnowledgeDescription: t("composerReferenceKnowledgeDescription"),
            composerReferenceKnowledgeSearch: t("composerReferenceKnowledgeSearch"),
            composerReferenceKnowledgeEmpty: t("composerReferenceKnowledgeEmpty"),
            composerBudgetEntry: t("composerBudgetEntry"),
            composerBudgetHint: t("composerBudgetHint"),
            composerBudgetTitle: t("composerBudgetTitle"),
            composerBudgetDescription: t("composerBudgetDescription"),
            composerBudgetMaxCallsLabel: t("composerBudgetMaxCallsLabel"),
            composerBudgetMaxCallsPlaceholder: t("composerBudgetMaxCallsPlaceholder"),
            composerBudgetClearMaxCalls: t("composerBudgetClearMaxCalls"),
            composerBudgetSave: t("composerBudgetSave"),
            composerBudgetCancel: t("composerBudgetCancel"),
            composerBudgetLoading: t("composerBudgetLoading"),
            composerBudgetLoadFailed: t("composerBudgetLoadFailed"),
          }}
          mentalModelEnabled={mentalModelEnabledForNextTurn}
          runtimeStatusEnabled={runtimeStatusEnabledForNextTurn}
          promptSuggestionEnabled={activePromptSuggestionEnabled}
          capabilityDisabled={!activeSessionId}
          onMentalModelEnabledChange={handleMentalModelEnabledChange}
          onRuntimeStatusEnabledChange={handleRuntimeStatusEnabledChange}
          onPromptSuggestionEnabledChange={handlePromptSuggestionEnabledChange}
          budget={composerBudgetControl ?? null}
          directSession={!financeSurface && agentDirectSessionMismatch && agentPrimaryDirectSessionId ? {
            id: agentPrimaryDirectSessionId,
            label: sessionBindingMismatchLine,
            onOpen: () => handleOpenDirectSession(agentPrimaryDirectSessionId),
            onPrefetch: () => handlePrefetchDirectSession(agentPrimaryDirectSessionId),
          } : null}
          group={standardGroupRoomActive && activeGroupRoom ? {
            title: activeGroupRoom.title,
            onManage: () => setGroupManageDialogOpen(true),
            teamId: activeGroupTeamOwned ? activeGroupTeam?.teamId : undefined,
            onOpenTeam: activeGroupTeamOwned && activeGroupTeam
              ? () => navigate(teamWorkspaceRoute(activeGroupTeam.teamId))
              : undefined,
          } : null}
        />
      ),
      permissionControl: !financeSurface && !verifiedCompanionMode && activeSessionAgent ? {
        value: activeSessionAgent.permissionPreset || "request_approval",
        disabled: (
          agentPermissionPresetMutation.isPending
          || activeSessionAgent.configSchemaVersion < 2
          || activeSessionAgent.configRevision < 1
          || !activeSessionAgent.configHash
        ),
        pending: (
          agentPermissionPresetMutation.isPending
          && agentPermissionPresetMutation.variables?.agentId === activeSessionAgent.agentId
        ),
        agentName: activeAgentDisplayName,
        onChange: (permissionPreset: AgentPermissionPreset) => {
          if (
            !activeSessionId
            || agentPermissionPresetMutation.isPending
            || activeSessionAgent.configSchemaVersion < 2
            || activeSessionAgent.configRevision < 1
            || !activeSessionAgent.configHash
          ) {
            return;
          }
          agentPermissionPresetMutation.mutate({
            agentId: activeSessionAgent.agentId,
            sessionId: activeSessionId,
            permissionPreset,
            expectedConfigRevision: activeSessionAgent.configRevision,
          });
        },
      } : undefined,
      llmControl: undefined,
      turnModelControl: financeSurface || verifiedCompanionMode ? undefined : turnModelControl,
      onOpenAgentModelConfig: !financeSurface && !verifiedCompanionMode && activeSessionAgent
        ? () => handleOpenAgentConfig(activeSessionAgent, sessionsById.get(activeSessionId ?? "") ?? null)
        : undefined,
      composerContextRing: financeSurface || verifiedCompanionMode ? null : composerContextRing,
      onOpenComposerContextDetail: !financeSurface && !verifiedCompanionMode && cacheDetailAvailable ? openCacheDetail : undefined,
      onCreateSession: !verifiedCompanionMode && selectedChatAgent ? () => handleCreateAgentSession(selectedChatAgent) : undefined,
      onOpenSideChat: ordinaryChangeRail && detail.sessionKind !== "child" ? openOrdinarySideChat : undefined,
      onOpenRailFile: ordinaryChangeRail && detail.sessionKind !== "child" ? openOrdinaryRailFile : undefined,
      slashCommandSuggestions: verifiedCompanionMode ? [] : slashCommandSuggestions,
      slashSkillsCatalogState: verifiedCompanionMode ? "ready" : slashSkillsCatalogState,
      composerReferenceOptions: verifiedCompanionMode ? [] : composerKnowledgeReferenceOptions,
      cancelComposerModeLabel: t("cancelEditMessage"),
      turnError: detail.lastTurnError,
      stopLabel: t("stop"),
      stopPendingLabel: t("stopPending"),
      safeGuidanceLabel: t("safeGuidance"),
      safeGuidancePendingLabel: t("safeGuidancePending"),
      interruptGuidanceLabel: t("interruptGuidance"),
      interruptGuidancePendingLabel: t("interruptGuidancePending"),
      editUserMessageLabel: t("editAndResendMessage"),
      onComposerChange: handleComposerChange,
      onAddComposerAttachments: handleAddComposerAttachments,
      onRemoveComposerAttachment: handleRemoveComposerAttachment,
      onRetryComposerAttachment: handleRetryComposerAttachmentUpload,
      onRetryComposerAttachmentUploads: handleRetryComposerAttachmentUploads,
      onAddComposerReference: handleAddComposerReference,
      onRemoveComposerReference: handleRemoveComposerReference,
      onEditUserMessage: handleEditUserMessage,
      onRegenerateAssistantMessage: handleRegenerateAssistantMessage,
      onSwitchMessageVersion: handleSwitchMessageVersion,
      onForkSessionFromNode: verifiedCompanionMode ? undefined : handleForkSessionFromNode,
      branchVersionSwitchDisabled: (
        sessionBusy
        || (switchHeadMutation.isPending
          && switchHeadMutation.variables?.sessionId === activeSessionId)
      ),
      regenerableAssistantMessageId,
      regenerateDisabled: sessionBusy || regenerateMutation.isPending || modelParametersSavePending,
      regeneratePending: (
        regenerateMutation.isPending
        && regenerateMutation.variables?.sessionId === activeSessionId
      ),
      onRetryTurn: handleRetryFailedTurn,
      retryTurnDisabled: sessionBusy || regenerateMutation.isPending || modelParametersSavePending,
      retryTurnPending: (
        regenerateMutation.isPending
        && regenerateMutation.variables?.sessionId === activeSessionId
      ),
      onCancelComposerMode: resolvedEditTarget ? handleCancelEditMessage : undefined,
      onLoadEarlierMessages: handleLoadEarlierSessionMessages,
      onSubmit: handleSubmitTurn,
      onStop: handleStopTurn,
      onSafeGuidance: () => handleSubmitGuidance("safe"),
      onInterruptGuidance: () => handleSubmitGuidance("interrupt"),
      onFollowupQueueUpdate: handleFollowupQueueUpdate,
      onFollowupQueueRemove: handleFollowupQueueRemove,
      onFollowupQueueMove: handleFollowupQueueMove,
      onFollowupQueueSteer: handleFollowupQueueSteer,
      onFollowupQueueSendNow: handleFollowupQueueSendNow,
      followupQueueSteerLabel: t("immediateSteer"),
    } : null),
    [
      activeAgentAvatarFallback,
      activeAgentAvatarImageUrl,
      activeAgentDisplayName,
      activeGroupRoom,
      activeGroupTeam,
      activeGroupTeamOwned,
      activePromptSuggestionEnabled,
      activeSessionAgent,
      activeSessionId,
      agentDirectSessionMismatch,
      agentPermissionPresetMutation,
      agentPrimaryDirectSessionId,
      cacheDetailAvailable,
      composerBudgetControl,
      composerContextRing,
      composerFocusRequest,
      composerKnowledgeReferenceOptions,
      knowledgeReferenceState,
      composerSessionReferenceOptions,
      currentTaskSummary,
      detail,
      financeSurface,
      handleAddComposerAttachments,
      handleAddComposerReference,
      handleCancelEditMessage,
      handleComposerChange,
      handleConversationStreamingFramePaint,
      handleCreateAgentSession,
      handleEditUserMessage,
      handleFollowupQueueMove,
      handleFollowupQueueRemove,
      handleFollowupQueueSendNow,
      handleFollowupQueueSteer,
      handleFollowupQueueUpdate,
      handleForkSessionFromNode,
      handleLoadEarlierSessionMessages,
      handleMentalModelEnabledChange,
      handleOpenDirectSession,
      handlePrefetchDirectSession,
      handlePromptSuggestionEnabledChange,
      handleRegenerateAssistantMessage,
      handleRemoveComposerAttachment,
      handleRemoveComposerReference,
      handleRetryComposerAttachmentUpload,
      handleRetryComposerAttachmentUploads,
      handleRetryFailedTurn,
      handleRuntimeStatusEnabledChange,
      handleStopTurn,
      handleSubmitGuidance,
      handleSubmitTurn,
      handleSwitchMessageVersion,
      lang,
      loadEarlierSessionMessagesMutation,
      mentalModelEnabledForNextTurn,
      navigate,
      openCacheDetail,
      openOrdinaryRailFile,
      openOrdinarySideChat,
      ordinaryChangeRail,
      regenerateMutation,
      regenerableAssistantMessageId,
      resolvedEditTarget,
      resolveConversationTurnAvatar,
      runtime,
      selectedChatAgent,
      sessionBusy,
      modelParametersSavePending,
      activeSessionAgent,
      handleOpenAgentConfig,
      sessionBindingMismatchLine,
      sessionTranscriptPending,
      setGroupManageDialogOpen,
      settleSessionComposerFocusRequest,
      slashCommandSuggestions,
      slashSkillsCatalogState,
      standardGroupRoomActive,
      switchHeadMutation,
      t,
      verifiedCompanionMode,
      companionConversationComposer,
    ],
  );

  return useMemo(() => {
    if (!conversationModel) {
      return null;
    }
    const model = conversationModel;
    const covered = {
      sessionId: true,
      title: true,
      phase: true,
      sessionWorkspacePath: true,
      messages: true,
      transcriptPending: true,
      hasEarlierMessages: true,
      earlierMessagesLoading: true,
      onStreamingFramePaint: true,
      assistantDisplayName: true,
      assistantAvatarImageUrl: true,
      assistantAvatarFallback: true,
      resolveTurnAvatar: true,
      userDisplayName: true,
      userAvatarPreset: true,
      userAvatarImageUrl: true,
      taskSummary: true,
      changedFiles: true,
      defaultFileContext: true,
      showHeader: true,
      showSessionOverview: true,
      companionMode: true,
      showMentalSnapshots: true,
      promptSuggestionEnabled: true,
      composerFocusSignal: true,
      onComposerFocusRequestSettled: true,
      composer: true,
      composerLeadingControl: true,
      permissionControl: true,
      llmControl: true,
      turnModelControl: true,
      onOpenAgentModelConfig: true,
      composerContextRing: true,
      onOpenComposerContextDetail: true,
      onCreateSession: true,
      onOpenSideChat: true,
      onOpenRailFile: true,
      slashCommandSuggestions: true,
      slashSkillsCatalogState: true,
      composerReferenceOptions: true,
      cancelComposerModeLabel: true,
      turnError: true,
      stopLabel: true,
      stopPendingLabel: true,
      safeGuidanceLabel: true,
      safeGuidancePendingLabel: true,
      interruptGuidanceLabel: true,
      interruptGuidancePendingLabel: true,
      editUserMessageLabel: true,
      onComposerChange: true,
      onAddComposerAttachments: true,
      onRemoveComposerAttachment: true,
      onRetryComposerAttachment: true,
      onRetryComposerAttachmentUploads: true,
      onAddComposerReference: true,
      onRemoveComposerReference: true,
      onEditUserMessage: true,
      onRegenerateAssistantMessage: true,
      onSwitchMessageVersion: true,
      onForkSessionFromNode: true,
      branchVersionSwitchDisabled: true,
      regenerableAssistantMessageId: true,
      regenerateDisabled: true,
      regeneratePending: true,
      onRetryTurn: true,
      retryTurnDisabled: true,
      retryTurnPending: true,
      onCancelComposerMode: true,
      onLoadEarlierMessages: true,
      onSubmit: true,
      onStop: true,
      onSafeGuidance: true,
      onInterruptGuidance: true,
      onFollowupQueueUpdate: true,
      onFollowupQueueRemove: true,
      onFollowupQueueMove: true,
      onFollowupQueueSteer: true,
      onFollowupQueueSendNow: true,
      followupQueueSteerLabel: true,
    } satisfies Record<keyof typeof model, true>;
    void covered;
    return {
      sessionId: model.sessionId,
      messages: model.messages,
      transcript: {
      title: model.title,
      phase: model.phase,
      sessionWorkspacePath: model.sessionWorkspacePath,
      transcriptPending: model.transcriptPending,
      hasEarlierMessages: model.hasEarlierMessages,
      earlierMessagesLoading: model.earlierMessagesLoading,
      onStreamingFramePaint: model.onStreamingFramePaint,
      showHeader: model.showHeader,
      showSessionOverview: model.showSessionOverview,
      showMentalSnapshots: model.showMentalSnapshots,
      companionMode: model.companionMode,
      turnError: model.turnError,
      onLoadEarlierMessages: model.onLoadEarlierMessages,
    },
      participants: {
      assistantDisplayName: model.assistantDisplayName,
      assistantAvatarImageUrl: model.assistantAvatarImageUrl,
      assistantAvatarFallback: model.assistantAvatarFallback,
      resolveTurnAvatar: model.resolveTurnAvatar,
      userDisplayName: model.userDisplayName,
      userAvatarPreset: model.userAvatarPreset,
      userAvatarImageUrl: model.userAvatarImageUrl,
      taskSummary: model.taskSummary,
      changedFiles: model.changedFiles,
      defaultFileContext: model.defaultFileContext,
    },
      composerChrome: {
      promptSuggestionEnabled: model.promptSuggestionEnabled,
      composerFocusSignal: model.composerFocusSignal,
      onComposerFocusRequestSettled: model.onComposerFocusRequestSettled,
      composer: model.composer,
      composerLeadingControl: model.composerLeadingControl,
      permissionControl: model.permissionControl,
      llmControl: model.llmControl,
      turnModelControl: model.turnModelControl,
      onOpenAgentModelConfig: model.onOpenAgentModelConfig,
      composerContextRing: model.composerContextRing,
      onOpenComposerContextDetail: model.onOpenComposerContextDetail,
      onCreateSession: model.onCreateSession,
      onOpenSideChat: model.onOpenSideChat,
      onOpenRailFile: model.onOpenRailFile,
      slashCommandSuggestions: model.slashCommandSuggestions,
      slashSkillsCatalogState: model.slashSkillsCatalogState,
      composerReferenceOptions: model.composerReferenceOptions,
      cancelComposerModeLabel: model.cancelComposerModeLabel,
      stopLabel: model.stopLabel,
      stopPendingLabel: model.stopPendingLabel,
      safeGuidanceLabel: model.safeGuidanceLabel,
      safeGuidancePendingLabel: model.safeGuidancePendingLabel,
      interruptGuidanceLabel: model.interruptGuidanceLabel,
      interruptGuidancePendingLabel: model.interruptGuidancePendingLabel,
      onComposerChange: model.onComposerChange,
      onAddComposerAttachments: model.onAddComposerAttachments,
      onRemoveComposerAttachment: model.onRemoveComposerAttachment,
      onRetryComposerAttachment: model.onRetryComposerAttachment,
      onRetryComposerAttachmentUploads: model.onRetryComposerAttachmentUploads,
      onAddComposerReference: model.onAddComposerReference,
      onRemoveComposerReference: model.onRemoveComposerReference,
      onSubmit: model.onSubmit,
      onStop: model.onStop,
      onSafeGuidance: model.onSafeGuidance,
      onInterruptGuidance: model.onInterruptGuidance,
    },
      turnActions: {
      editUserMessageLabel: model.editUserMessageLabel,
      onEditUserMessage: model.onEditUserMessage,
      onRegenerateAssistantMessage: model.onRegenerateAssistantMessage,
      onSwitchMessageVersion: model.onSwitchMessageVersion,
      onForkSessionFromNode: model.onForkSessionFromNode,
      branchVersionSwitchDisabled: model.branchVersionSwitchDisabled,
      regenerableAssistantMessageId: model.regenerableAssistantMessageId,
      regenerateDisabled: model.regenerateDisabled,
      regeneratePending: model.regeneratePending,
      onRetryTurn: model.onRetryTurn,
      retryTurnDisabled: model.retryTurnDisabled,
      retryTurnPending: model.retryTurnPending,
      onCancelComposerMode: model.onCancelComposerMode,
      onFollowupQueueUpdate: model.onFollowupQueueUpdate,
      onFollowupQueueRemove: model.onFollowupQueueRemove,
      onFollowupQueueMove: model.onFollowupQueueMove,
      onFollowupQueueSteer: model.onFollowupQueueSteer,
      onFollowupQueueSendNow: model.onFollowupQueueSendNow,
      followupQueueSteerLabel: model.followupQueueSteerLabel,
    },
    } satisfies ChatConversationSurfaceModel;
  }, [conversationModel]);
}
