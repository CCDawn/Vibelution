import type { DragEvent, MouseEvent } from "react";

import type { AgentInstance, ConversationSummary, SessionReferenceAttachment, SessionSummary } from "../api/types";
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
  sessionComposerErrors: Record<string, string>;
  sessionsById: Map<string, SessionSummary>;
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
  isBusyPhase: (value: string | null | undefined) => boolean;
  onCancelRename: () => void;
  onContextMenu: (event: MouseEvent<HTMLDivElement>, session: SessionSummary) => void;
  onDragReference: (event: DragEvent<HTMLElement>, reference: SessionReferenceAttachment) => void;
  onOpen: (sessionId: string) => void;
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
    return existingSession;
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
  sessionComposerErrors,
  sessionsById,
  statusLabel,
  formatTime,
  t,
  avatarImageUrlFrom,
  avatarInitials,
  buildSessionReferencePayload,
  isBusyPhase,
  onCancelRename,
  onContextMenu,
  onDragReference,
  onOpen,
  onRenameTitleChange,
  onSubmitRename,
}: DirectSessionIndexListProps) {
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
            editing={isEditingTitle}
            editingTitle={editingSessionTitle}
            itemMessage={sessionView.itemMessage}
            itemIsNotice={sessionView.itemIsNotice}
            missingAgentMessage={sessionView.missingAgentMessage}
            renamePending={sessionRenamePending}
            session={session}
            sessionAvatarFallback={avatarInitials(session.agentCode, sessionView.sessionTitle)}
            sessionAvatarImageUrl={sessionAvatarImageUrl}
            sessionDisplay={sessionView.sessionDisplay}
            sessionSummary={sessionView.sessionSummary}
            sessionTitle={sessionView.sessionTitle}
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
            onRenameTitleChange={onRenameTitleChange}
            onSubmitRename={onSubmitRename}
          />
        );
      })}
    </>
  );
}
