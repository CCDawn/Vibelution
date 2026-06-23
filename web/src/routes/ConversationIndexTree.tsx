import type { DragEvent, MouseEvent } from "react";

import type {
  AgentInstance,
  ConversationSummary,
  SessionReferenceAttachment,
  SessionSummary,
  Team,
} from "../api/types";
import type { TranslationKey } from "../i18n/dictionary";
import type { ModelLabelResolver } from "./agentDisplay";
import type { ConversationIndexDynamicGroupKey, ConversationIndexGroup, ConversationIndexGroupKey, ConversationIndexTeam } from "./conversationIndexModel";
import { isConfiguredConversationIndexTeam } from "./conversationIndexModel";
import { ConversationIndexSection } from "./ConversationIndexSection";
import { DirectSessionIndexList } from "./DirectSessionIndexList";
import {
  GroupConversationIndexItem,
  TeamConversationIndexItem,
} from "./GroupSessionIndexItems";
import styles from "./ChatCodingRoute.module.css";

type ConversationIndexTreeProps = {
  activeGroupRoomId: string;
  activeSessionId: string | null;
  addToReviewSucceededLabel: string;
  agentsById: Map<string, AgentInstance>;
  avatarImageUrlFrom: (...sources: unknown[]) => string;
  avatarInitials: (agentCode?: string, name?: string, fallback?: string) => string;
  buildSessionReferencePayload: (
    session: SessionSummary,
    displayName: string,
    summary: string,
  ) => SessionReferenceAttachment;
  collapsedConversationGroups: Record<string, boolean>;
  conversationGroupLabel: (groupKey: ConversationIndexGroupKey, lang: "zh" | "en") => string;
  deleteBusyLabel: string;
  editingSessionId: string | null;
  editingSessionTitle: string;
  filteredConversationsCount: number;
  filteredStandaloneGroupConversations: ConversationSummary[];
  filteredTeams: ConversationIndexTeam[];
  formatTime: (value: string) => string;
  groupPanelActive: boolean;
  groupedConversations: ConversationIndexGroup[];
  isBusyPhase: (value: string | null | undefined) => boolean;
  lang: "zh" | "en";
  renamePending: boolean;
  renameSessionId: string;
  resolveModelLabel?: ModelLabelResolver;
  searchHasTerm: boolean;
  sessionComposerErrors: Record<string, string>;
  sessionsById: Map<string, SessionSummary>;
  statusLabel: (status: string) => string;
  t: (key: TranslationKey) => string;
  onCancelRename: () => void;
  onContextMenu: (event: MouseEvent<HTMLDivElement>, session: SessionSummary) => void;
  onDragReference: (event: DragEvent<HTMLElement>, reference: SessionReferenceAttachment) => void;
  onOpenDirectSession: (sessionId: string) => void;
  onOpenGroupRoom: (roomId: string) => void;
  onRenameTitleChange: (title: string) => void;
  onSubmitRename: (session: SessionSummary) => void;
  onToggleConversationGroup: (groupKey: ConversationIndexDynamicGroupKey) => void;
};

function roomIdFromConversation(conversation: ConversationSummary) {
  return conversation.roomId || conversation.conversationId;
}

function teamRouteFor(team: Team) {
  return `/teams?team=${encodeURIComponent(team.teamId)}`;
}

export function ConversationIndexTree({
  activeGroupRoomId,
  activeSessionId,
  addToReviewSucceededLabel,
  agentsById,
  avatarImageUrlFrom,
  avatarInitials,
  buildSessionReferencePayload,
  collapsedConversationGroups,
  conversationGroupLabel,
  deleteBusyLabel,
  editingSessionId,
  editingSessionTitle,
  filteredConversationsCount,
  filteredStandaloneGroupConversations,
  filteredTeams,
  formatTime,
  groupPanelActive,
  groupedConversations,
  isBusyPhase,
  lang,
  renamePending,
  renameSessionId,
  resolveModelLabel,
  searchHasTerm,
  sessionComposerErrors,
  sessionsById,
  statusLabel,
  t,
  onCancelRename,
  onContextMenu,
  onDragReference,
  onOpenDirectSession,
  onOpenGroupRoom,
  onRenameTitleChange,
  onSubmitRename,
  onToggleConversationGroup,
}: ConversationIndexTreeProps) {
  const configuredTeams = filteredTeams.filter(isConfiguredConversationIndexTeam);
  const setupTeams = filteredTeams.filter((team) => !isConfiguredConversationIndexTeam(team));

  return (
    <>
      {filteredConversationsCount ? groupedConversations.map((group) => {
        const collapsed = !searchHasTerm && collapsedConversationGroups[group.groupKey];
        const groupRoomConversations = group.items.filter((conversation) => conversation.type === "group_room");
        const directSessionConversations = group.items.filter((conversation) => conversation.type !== "group_room");
        return (
          <ConversationIndexSection
            key={group.groupKey}
            count={group.items.length}
            expanded={!collapsed}
            label={group.label}
            onToggle={() => onToggleConversationGroup(group.groupKey)}
          >
            {groupRoomConversations.map((conversation) => {
              const roomId = roomIdFromConversation(conversation);
              return (
                <GroupConversationIndexItem
                  key={`group-${roomId}`}
                  active={activeGroupRoomId === roomId}
                  conversation={conversation}
                  kindLabel={lang === "zh" ? "群聊" : "Group"}
                  fallbackSummary={lang === "zh" ? "群聊会话" : "Group conversation"}
                  lang={lang}
                  roomId={roomId}
                  statusLabel={statusLabel}
                  formatTime={formatTime}
                  onOpen={onOpenGroupRoom}
                />
              );
            })}
            <DirectSessionIndexList
              activeSessionId={activeSessionId}
              addToReviewSucceededLabel={addToReviewSucceededLabel}
              agentsById={agentsById}
              avatarImageUrlFrom={avatarImageUrlFrom}
              avatarInitials={avatarInitials}
              buildSessionReferencePayload={buildSessionReferencePayload}
              conversations={directSessionConversations}
              deleteBusyLabel={deleteBusyLabel}
              editingSessionId={editingSessionId}
              editingSessionTitle={editingSessionTitle}
              formatTime={formatTime}
              groupPanelActive={groupPanelActive}
              isBusyPhase={isBusyPhase}
              lang={lang}
              renamePending={renamePending}
              renameSessionId={renameSessionId}
              resolveModelLabel={resolveModelLabel}
              sessionComposerErrors={sessionComposerErrors}
              sessionsById={sessionsById}
              statusLabel={statusLabel}
              t={t}
              onCancelRename={onCancelRename}
              onContextMenu={onContextMenu}
              onDragReference={onDragReference}
              onOpen={onOpenDirectSession}
              onRenameTitleChange={onRenameTitleChange}
              onSubmitRename={onSubmitRename}
            />
          </ConversationIndexSection>
        );
      }) : null}
      {configuredTeams.length ? (
        <ConversationIndexSection
          className={styles.teamTreeGroup}
          count={configuredTeams.length}
          expanded={searchHasTerm || !collapsedConversationGroups.teams}
          label={conversationGroupLabel("teams", lang === "zh" ? "zh" : "en")}
          onToggle={() => onToggleConversationGroup("teams")}
        >
          {configuredTeams.map((team) => {
            const roomId = String(team.linkedChatRoomId ?? "").trim();
            return (
              <TeamConversationIndexItem
                key={team.teamId}
                active={Boolean(roomId && activeGroupRoomId === roomId)}
                lang={lang}
                roomId={roomId}
                team={team}
                teamRoute={teamRouteFor(team)}
                statusLabel={statusLabel}
                onOpen={onOpenGroupRoom}
              />
            );
          })}
        </ConversationIndexSection>
      ) : null}
      {setupTeams.length ? (
        <ConversationIndexSection
          className={styles.teamTreeGroup}
          count={setupTeams.length}
          expanded={searchHasTerm || !collapsedConversationGroups.setupTeams}
          label={conversationGroupLabel("setupTeams", lang === "zh" ? "zh" : "en")}
          onToggle={() => onToggleConversationGroup("setupTeams")}
        >
          {setupTeams.map((team) => {
            const roomId = String(team.linkedChatRoomId ?? "").trim();
            return (
              <TeamConversationIndexItem
                key={team.teamId}
                active={Boolean(roomId && activeGroupRoomId === roomId)}
                lang={lang}
                roomId={roomId}
                team={team}
                teamRoute={teamRouteFor(team)}
                statusLabel={statusLabel}
                onOpen={onOpenGroupRoom}
              />
            );
          })}
        </ConversationIndexSection>
      ) : null}
      {filteredStandaloneGroupConversations.length ? (
        <ConversationIndexSection
          count={filteredStandaloneGroupConversations.length}
          expanded={searchHasTerm || !collapsedConversationGroups.standaloneGroups}
          label={conversationGroupLabel("standaloneGroups", lang === "zh" ? "zh" : "en")}
          onToggle={() => onToggleConversationGroup("standaloneGroups")}
        >
          {filteredStandaloneGroupConversations.map((conversation) => {
            const roomId = roomIdFromConversation(conversation);
            return (
              <GroupConversationIndexItem
                key={`standalone-group-${roomId}`}
                active={activeGroupRoomId === roomId}
                conversation={conversation}
                kindLabel={lang === "zh" ? "群" : "Group"}
                fallbackSummary={lang === "zh" ? "未绑定团队的群聊" : "Group without a Team"}
                lang={lang}
                roomId={roomId}
                statusLabel={statusLabel}
                formatTime={formatTime}
                onOpen={onOpenGroupRoom}
              />
            );
          })}
        </ConversationIndexSection>
      ) : null}
    </>
  );
}
