import type { DragEvent, MouseEvent } from "react";

import type { AgentInstance, ConversationSummary, SessionReferenceAttachment, SessionSummary, Team } from "../api/types";
import type { TranslationKey } from "../i18n/dictionary";
import type { ModelLabelResolver } from "./agentDisplay";
import { DirectSessionIndexItem, buildDirectSessionIndexViewModel } from "./DirectSessionIndexItem";

type DirectSessionIndexListProps = {
  activeSessionId: string | null;
  addToReviewSucceededLabel: string;
  agentsById: Map<string, AgentInstance>;
  conversations: ConversationSummary[];
  deleteBusyLabel: string;
  editingSessionId: string | null;
  editingSessionTitle: string;
  groupPanelActive: boolean;
  lang: "zh" | "en";
  renameSessionId: string;
  renamePending: boolean;
  resolveModelLabel?: ModelLabelResolver;
  /** Session ids with an active runtime chat_turn. */
  runtimeRunningSessionIds?: readonly string[];
  sessionComposerErrors: Record<string, string>;
  /** Session ids waiting on tool/permission approval. */
  sessionIdsNeedingApproval?: readonly string[];
  sessionsById: Map<string, SessionSummary>;
  teams?: Team[];
  statusLabel: (status: string) => string;
  formatTime: (value: string) => string;
  t: (key: TranslationKey) => string;
  avatarImageUrlFrom: (...sources: unknown[]) => string;
  avatarInitials: (agentCode?: string, name?: string, fallback?: string) => string;
  buildSessionReferencePayload: (
    session: SessionSummary,
    displayName: string,
    summary: string,
  ) => SessionReferenceAttachment;
  contextMenuSessionId: string;
  isBusyPhase: (value: string | null | undefined) => boolean;
  onCancelRename: () => void;
  onContextMenu: (event: MouseEvent<HTMLDivElement>, session: SessionSummary) => void;
  onDragReference: (event: DragEvent<HTMLElement>, reference: SessionReferenceAttachment) => void;
  onOpen: (sessionId: string) => void;
  onPrefetch?: (sessionId: string) => void;
  onRenameTitleChange: (title: string) => void;
  onSubmitRename: (session: SessionSummary) => void;
};

export function conversationToSessionSummary(
  conversation: ConversationSummary,
  sessionsById: Map<string, SessionSummary>,
): SessionSummary {
  const sessionId = conversation.directSessionId || conversation.conversationId;
  const existingSession = sessionsById.get(sessionId);
  if (existingSession) {
    let nextSession = existingSession;
    function patchExistingSession(patch: Partial<SessionSummary>) {
      const baseSession = nextSession === existingSession ? existingSession : nextSession;
      nextSession = { ...baseSession, ...patch };
    }

    const agentAvatarImagePath = existingSession.agentAvatarImagePath || conversation.agentAvatarImagePath;
    const agentAvatarImageUrl = existingSession.agentAvatarImageUrl || conversation.agentAvatarImageUrl;
    if (agentAvatarImagePath !== existingSession.agentAvatarImagePath) {
      patchExistingSession({
        agentAvatarImagePath,
      });
    }
    if (agentAvatarImageUrl !== existingSession.agentAvatarImageUrl) {
      patchExistingSession({
        agentAvatarImageUrl,
      });
    }
    if (existingSession.sourceRef === undefined && conversation.sourceRef !== undefined) {
      patchExistingSession({ sourceRef: conversation.sourceRef });
    }
    if (existingSession.projectionEdit === undefined && conversation.projectionEdit !== undefined) {
      patchExistingSession({ projectionEdit: conversation.projectionEdit });
    }
    if (existingSession.agentSourceRef === undefined && conversation.agentSourceRef !== undefined) {
      patchExistingSession({ agentSourceRef: conversation.agentSourceRef });
    }
    if (existingSession.conversationIndexVisibility === undefined && conversation.conversationIndexVisibility !== undefined) {
      patchExistingSession({ conversationIndexVisibility: conversation.conversationIndexVisibility });
    }
    if (existingSession.conversationIndexKind === undefined && conversation.conversationIndexKind !== undefined) {
      patchExistingSession({ conversationIndexKind: conversation.conversationIndexKind });
    }
    if (existingSession.conversationIndexErrors === undefined && conversation.conversationIndexErrors !== undefined) {
      patchExistingSession({ conversationIndexErrors: conversation.conversationIndexErrors });
    }
    const conversationTeam = conversation as ConversationSummary & { teamId?: string; teamName?: string };
    if (!String(existingSession.teamId || "").trim() && String(conversationTeam.teamId || "").trim()) {
      patchExistingSession({
        teamId: conversationTeam.teamId,
        teamName: conversationTeam.teamName || existingSession.teamName,
      });
    }
    if (!String(existingSession.teamName || "").trim() && String(conversationTeam.teamName || "").trim()) {
      patchExistingSession({ teamName: conversationTeam.teamName });
    }
    return nextSession;
  }
  return {
    id: sessionId,
    title: conversation.title,
    agentId: conversation.agentId,
    agentCode: conversation.agentCode,
    agentPrimaryMode: conversation.agentPrimaryMode,
    agentRoleKey: conversation.agentRoleKey,
    agentPromptTemplateId: conversation.agentPromptTemplateId,
    agentInboxPendingCount: conversation.agentInboxPendingCount,
    agentAvatarImagePath: conversation.agentAvatarImagePath,
    agentAvatarImageUrl: conversation.agentAvatarImageUrl,
    agentDisplayName: conversation.agentDisplayName,
    workspacePath: conversation.workspacePath,
    status: conversation.status,
    taskSummary: conversation.summary,
    lastActive: conversation.updatedAt,
    updatedAt: conversation.updatedAt,
    currentPhase: conversation.status,
    dialogueModelId: conversation.dialogueModelId,
    agentMissing: conversation.agentMissing,
    agentStatusCode: conversation.agentStatusCode,
    agentStatusMessage: conversation.agentStatusMessage,
    sourceRef: conversation.sourceRef,
    projectionEdit: conversation.projectionEdit,
    agentSourceRef: conversation.agentSourceRef,
    conversationIndexVisibility: conversation.conversationIndexVisibility,
    conversationIndexKind: conversation.conversationIndexKind,
    conversationIndexErrors: conversation.conversationIndexErrors,
    teamId: (conversation as ConversationSummary & { teamId?: string }).teamId,
    teamName: (conversation as ConversationSummary & { teamName?: string }).teamName,
  };
}

export function DirectSessionIndexList({
  activeSessionId,
  addToReviewSucceededLabel,
  agentsById,
  conversations,
  deleteBusyLabel,
  editingSessionId,
  editingSessionTitle,
  groupPanelActive,
  lang,
  renameSessionId,
  renamePending,
  resolveModelLabel,
  runtimeRunningSessionIds = [],
  sessionComposerErrors,
  sessionIdsNeedingApproval = [],
  sessionsById,
  teams = [],
  statusLabel,
  formatTime,
  t,
  avatarImageUrlFrom,
  avatarInitials,
  buildSessionReferencePayload,
  contextMenuSessionId,
  isBusyPhase,
  onCancelRename,
  onContextMenu,
  onDragReference,
  onOpen,
  onPrefetch,
  onRenameTitleChange,
  onSubmitRename,
}: DirectSessionIndexListProps) {
  const approvalSessionIds = new Set(
    sessionIdsNeedingApproval.map((id) => String(id || "").trim()).filter(Boolean),
  );
  const runtimeSessionIds = new Set(
    runtimeRunningSessionIds.map((id) => String(id || "").trim()).filter(Boolean),
  );
  return (
    <>
      {conversations.map((conversation) => {
        const session = conversationToSessionSummary(conversation, sessionsById);
        const sessionIsBusy = isBusyPhase(session.currentPhase || session.status);
        const sessionRenamePending = renamePending && renameSessionId === session.id;
        const isEditingTitle = editingSessionId === session.id;
        const itemError = sessionComposerErrors[session.id] ?? "";
        const sessionAgent = session.agentId ? agentsById.get(session.agentId) : undefined;
        const sessionAvatarImageUrl = avatarImageUrlFrom(sessionAgent, session);
        const sessionView = buildDirectSessionIndexViewModel({
          addToReviewSucceededLabel,
          agent: sessionAgent,
          deleteBusyLabel,
          itemError,
          lang,
          resolveModelLabel,
          session,
          sessionBusy: sessionIsBusy,
        });
        return (
          <DirectSessionIndexItem
            key={session.id}
            active={!groupPanelActive && activeSessionId === session.id}
            contextMenuActive={contextMenuSessionId === session.id}
            editing={isEditingTitle}
            editingTitle={editingSessionTitle}
            itemMessage={sessionView.itemMessage}
            itemIsNotice={sessionView.itemIsNotice}
            missingAgentMessage={sessionView.missingAgentMessage}
            needsApproval={approvalSessionIds.has(session.id)}
            isRuntimeRunning={runtimeSessionIds.has(session.id)}
            renamePending={sessionRenamePending}
            session={session}
            sessionAvatarFallback={avatarInitials(session.agentCode, sessionView.sessionTitle)}
            sessionAvatarImageUrl={sessionAvatarImageUrl}
            sessionDisplay={sessionView.sessionDisplay}
            sessionSummary={sessionView.sessionSummary}
            sessionTitle={sessionView.sessionTitle}
            teams={teams}
            lang={lang}
            statusLabel={statusLabel}
            formatTime={formatTime}
            t={t}
            onCancelRename={onCancelRename}
            onContextMenu={onContextMenu}
            onDragStart={(event) =>
              onDragReference(
                event,
                buildSessionReferencePayload(
                  session,
                  sessionView.sessionAgentMeta || sessionView.sessionDisplay.name,
                  sessionView.sessionSummary,
                ),
              )}
            onOpen={onOpen}
            onPrefetch={onPrefetch}
            onRenameTitleChange={onRenameTitleChange}
            onSubmitRename={onSubmitRename}
          />
        );
      })}
    </>
  );
}
