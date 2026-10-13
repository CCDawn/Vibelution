/**
 * Conversation index body: sort/timeline controls, pinned and day buckets,
 * archived rail, agent directory, and session/agent context menus.
 * Extracted from ChatCodingRouteWorkbench with identical behavior.
 * Shares ChatCodingRoute.styles instead of copying the session-list map.
 */
import { ListTree } from "lucide-react";
import {
  lazy,
  Suspense,
  type Dispatch,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
  type SetStateAction,
} from "react";

import type {
  AgentInstance,
  ConversationSummary,
  SessionSummary,
  Team,
} from "../../api/types";
import { VIconButton, VStringSelect } from "../../components/vui";
import type { TranslationKey } from "../../i18n/dictionary";
import { AgentConversationDirectory } from "../AgentConversationDirectory";
import type { AgentContextMenuState } from "../AgentContextMenu";
import { ConversationIndexSection } from "../ConversationIndexSection";
import { ConversationIndexTree } from "../ConversationIndexTree";
import { DirectSessionIndexList } from "../DirectSessionIndexList";
import {
  conversationGroupLabel,
  isSessionArchived,
  sessionToConversationSummary,
  type ConversationIndexDynamicGroupKey,
  type ConversationIndexGroup,
  type ConversationIndexTeam,
} from "../conversationIndexModel";
import type { ModelLabelResolver } from "../agentDisplay";
import styles from "../ChatCodingRoute.styles";
import { ArchivedSessionRail } from "./ArchivedSessionRail";
import { ChatConversationIndexPanelContent } from "./ChatConversationIndexPanelContent";
import {
  buildSessionReferencePayload,
  startSessionReferenceDrag,
} from "./chatComposerSubmitModel";
import { isBusyPhase } from "./chatCodingRouteViewModel";
import {
  avatarImageUrlFrom,
  avatarInitials,
} from "./chatRoutePresentation";
import {
  groupSessionsByTimeline,
  splitPinnedSessions,
  type SessionListDateBucket,
} from "./sessionListGrouping";
import {
  normalizeSessionListSortBy,
  type SessionListPreferences,
} from "./sessionListPreferences";
import { SessionBulkOperationsPanel } from "./SessionBulkOperationsPanel";
import type { SessionBulkNotice } from "./useChatSessionBulkSelection";
import type { AgentRenameDraft } from "./useChatAgentDirectoryActions";
import type { SessionContextMenuState } from "./useChatSessionRenameMenu";

const SessionContextMenu = lazy(() =>
  import("../SessionContextMenu").then((module) => ({
    default: module.SessionContextMenu,
  })),
);
const AgentRenameDialog = lazy(() =>
  import("../AgentRenameDialog").then((module) => ({
    default: module.AgentRenameDialog,
  })),
);
const AgentContextMenu = lazy(() =>
  import("../AgentContextMenu").then((module) => ({
    default: module.AgentContextMenu,
  })),
);

type PendingSessionMutation = {
  isPending: boolean;
  variables?: { sessionId?: string } | undefined;
};

type ArchiveSessionMutation = PendingSessionMutation & {
  mutate: (variables: { sessionId: string; archive: boolean }) => void;
};

type DeleteSessionMutation = PendingSessionMutation & {
  mutate: (
    variables: { sessionId: string },
    options?: { onSettled?: () => void },
  ) => void;
};

export type ChatConversationIndexPanelProps = {
  activeGroupRoomId: string;
  activeSessionId: string | null;
  agentContextMenu: AgentContextMenuState | null;
  agentRenameDraft: AgentRenameDraft | null;
  agentsById: Map<string, AgentInstance>;
  allVisibleSessions: SessionSummary[];
  allVisibleSessionsSelected: boolean;
  archiveVisibleAgents: AgentInstance[];
  archivedSessions: SessionSummary[];
  archivedSessionsPending: boolean;
  archivedTotalEstimate: number;
  beginRenameSession: (session: SessionSummary) => void;
  bulkDeleteSessionsMutation: { isPending: boolean };
  bulkRemoveSessions: () => Promise<void>;
  bulkSessionPending: boolean;
  cancelAgentRename: () => void;
  cancelRenameSession: () => void;
  clearBulkSessions: () => void;
  collapsedConversationGroups: Record<string, boolean>;
  contextMenuAddToReviewDisabled: boolean;
  contextMenuAddToReviewPending: boolean;
  contextMenuAgentArchivePending: boolean;
  contextMenuClearHistoryDisabled: boolean;
  contextMenuClearHistoryPending: boolean;
  contextMenuClearHistoryVisible: boolean;
  contextMenuDeleteDisabled: boolean;
  contextMenuSession: SessionSummary | undefined;
  contextMenuSessionId: string;
  conversationIndexLoading: boolean;
  createSessionMutation: { isPending: boolean };
  deleteSessionMutation: DeleteSessionMutation;
  directoryFilterText: string;
  editingSessionId: string | null;
  editingSessionTitle: string;
  filteredConversations: ConversationSummary[];
  filteredStandaloneGroupConversations: ConversationSummary[];
  filteredTeams: ConversationIndexTeam[];
  formatConversationIndexTime: (value: string) => string;
  groupPanelActive: boolean;
  groupedGroupConversationCount: number;
  groupedGroupConversations: ConversationIndexGroup[];
  handleAddSessionToReview: (session: SessionSummary) => void;
  handleArchiveAgent: (agent: AgentInstance) => void;
  handleArchiveSession: (session: SessionSummary) => void;
  handleClearSessionHistory: (session: SessionSummary) => void;
  handleCreateAgentSession: (agent: AgentInstance) => void;
  handleDeleteArchivedSession: (session: SessionSummary) => void;
  handleDeleteAllArchivedSessions: () => void;
  handleDeleteSession: (session: SessionSummary) => void;
  handleOpenAgent: (agent: AgentInstance) => boolean;
  handleOpenAgentConfig: (agent: AgentInstance, latestSession: SessionSummary | null) => void;
  handleOpenAgentLatestSession: (agent: AgentInstance, latestSession: SessionSummary | null) => void;
  handleOpenDirectSession: (sessionId: string) => void;
  handleOpenGroupRoom: (roomId: string) => void;
  handlePrefetchDirectSession: (sessionId: string) => void;
  handleRenameAgent: (agent: AgentInstance) => void;
  handleTogglePinSession: (session: SessionSummary) => void;
  lang: "zh" | "en";
  onOpenReportLibrary: ((session: SessionSummary) => void) | undefined;
  openAgentContextMenu: (
    event: ReactMouseEvent<HTMLElement>,
    agent: AgentInstance,
    latestSession: SessionSummary | null,
  ) => void;
  openSessionAgentConfig: (session: SessionSummary) => void;
  openSessionContextMenu: (event: ReactMouseEvent<HTMLElement>, session: SessionSummary) => void;
  pinSessionMutation: PendingSessionMutation;
  railSectionCollapsed: Record<string, boolean>;
  renameAgentMutation: { isPending: boolean };
  renameSessionMutation: PendingSessionMutation;
  resolveModelLabel: ModelLabelResolver;
  runtimeRunningSessionIds: readonly string[];
  searchHasTerm: boolean;
  selectVisibleBulkSessions: () => void;
  selectedBulkSessionIds: ReadonlySet<string>;
  selectedBulkSessions: readonly string[];
  selectedChatAgentId: string;
  sessionArchiveMutation: ArchiveSessionMutation;
  sessionBulkCopy: {
    bulkSelected: string;
    bulkClear: string;
    bulkSelectVisible: string;
    bulkRemove: string;
    bulkWorking: string;
    bulkRemoveConfirm: string;
    cancelCreate: string;
  };
  sessionBulkNotice: SessionBulkNotice | null;
  sessionComposerErrors: Record<string, string>;
  sessionContextMenu: SessionContextMenuState | null;
  sessionIdsNeedingApproval: readonly string[];
  sessionListPrefs: SessionListPreferences;
  sessionsBlockingError: boolean;
  sessionsById: Map<string, SessionSummary>;
  sessionsErrorMessage: string;
  sessionsTransientError: boolean;
  setAgentContextMenu: Dispatch<SetStateAction<AgentContextMenuState | null>>;
  setAgentRenameDraftName: (draftName: string) => void;
  setEditingSessionTitle: Dispatch<SetStateAction<string>>;
  setRailSectionCollapsed: Dispatch<SetStateAction<Record<string, boolean>>>;
  setSessionContextMenu: Dispatch<SetStateAction<SessionContextMenuState | null>>;
  setSessionListPrefs: Dispatch<SetStateAction<SessionListPreferences>>;
  showArchivedSessions: boolean;
  statusLabel: (status: string) => string;
  submitAgentRename: () => void;
  submitRenameSession: (session: SessionSummary) => void;
  t: (key: TranslationKey) => string;
  teamRoomsByTeamId: ReadonlyMap<string, readonly ConversationSummary[]>;
  teams: Team[];
  toggleBulkSession: (sessionId: string, selected: boolean, extendRange?: boolean) => void;
  toggleConversationGroup: (groupKey: ConversationIndexDynamicGroupKey) => void;
  visibleDirectSessionIds: readonly string[];
};

export function ChatConversationIndexPanel({
  activeGroupRoomId,
  activeSessionId,
  agentContextMenu,
  agentRenameDraft,
  agentsById,
  allVisibleSessions,
  allVisibleSessionsSelected,
  archiveVisibleAgents,
  archivedSessions,
  archivedSessionsPending,
  archivedTotalEstimate,
  beginRenameSession,
  bulkDeleteSessionsMutation,
  bulkRemoveSessions,
  bulkSessionPending,
  cancelAgentRename,
  cancelRenameSession,
  clearBulkSessions,
  collapsedConversationGroups,
  contextMenuAddToReviewDisabled,
  contextMenuAddToReviewPending,
  contextMenuAgentArchivePending,
  contextMenuClearHistoryDisabled,
  contextMenuClearHistoryPending,
  contextMenuClearHistoryVisible,
  contextMenuDeleteDisabled,
  contextMenuSession,
  contextMenuSessionId,
  conversationIndexLoading,
  createSessionMutation,
  deleteSessionMutation,
  directoryFilterText,
  editingSessionId,
  editingSessionTitle,
  filteredConversations,
  filteredStandaloneGroupConversations,
  filteredTeams,
  formatConversationIndexTime,
  groupPanelActive,
  groupedGroupConversationCount,
  groupedGroupConversations,
  handleAddSessionToReview,
  handleArchiveAgent,
  handleArchiveSession,
  handleClearSessionHistory,
  handleCreateAgentSession,
  handleDeleteAllArchivedSessions,
  handleDeleteArchivedSession,
  handleDeleteSession,
  handleOpenAgent,
  handleOpenAgentConfig,
  handleOpenAgentLatestSession,
  handleOpenDirectSession,
  handleOpenGroupRoom,
  handlePrefetchDirectSession,
  handleRenameAgent,
  handleTogglePinSession,
  lang,
  onOpenReportLibrary,
  openAgentContextMenu,
  openSessionAgentConfig,
  openSessionContextMenu,
  pinSessionMutation,
  railSectionCollapsed,
  renameAgentMutation,
  renameSessionMutation,
  resolveModelLabel,
  runtimeRunningSessionIds,
  searchHasTerm,
  selectVisibleBulkSessions,
  selectedBulkSessionIds,
  selectedBulkSessions,
  selectedChatAgentId,
  sessionArchiveMutation,
  sessionBulkCopy,
  sessionBulkNotice,
  sessionComposerErrors,
  sessionContextMenu,
  sessionIdsNeedingApproval,
  sessionListPrefs,
  sessionsBlockingError,
  sessionsById,
  sessionsErrorMessage,
  sessionsTransientError,
  setAgentContextMenu,
  setAgentRenameDraftName,
  setEditingSessionTitle,
  setRailSectionCollapsed,
  setSessionContextMenu,
  setSessionListPrefs,
  showArchivedSessions,
  statusLabel,
  submitAgentRename,
  submitRenameSession,
  t,
  teamRoomsByTeamId,
  teams,
  toggleBulkSession,
  toggleConversationGroup,
  visibleDirectSessionIds,
}: ChatConversationIndexPanelProps) {
  const toggleRailSection = (key: string) => {
    setRailSectionCollapsed((current) => ({ ...current, [key]: !current[key] }));
  };
  const timelineBucketLabel = (bucket: SessionListDateBucket) => {
    switch (bucket) {
      case "today":
        return t("sessionListTimelineToday");
      case "yesterday":
        return t("sessionListTimelineYesterday");
      case "thisWeek":
        return t("sessionListTimelineThisWeek");
      default:
        return t("sessionListTimelineEarlier");
    }
  };
  // Pinned-first split plus optional day buckets over the loaded page; the
  // backend already orders pinned first, the split only isolates the section.
  const sessionListRail = (() => {
    const railSessions = allVisibleSessions.filter((session) => !isSessionArchived(session));
    const { pinned, unpinned } = splitPinnedSessions(railSessions);
    const timelineGroups = showArchivedSessions || !sessionListPrefs.timelineGrouping
      ? []
      : groupSessionsByTimeline(unpinned, Date.now());
    const renderSessionList = (
      sessions: SessionSummary[],
      renderTrailingActions?: (session: SessionSummary) => ReactNode,
    ) => {
      const listSessionsById = new Map(sessionsById);
      for (const session of sessions) {
        const existing = listSessionsById.get(session.id);
        listSessionsById.set(session.id, existing ? { ...existing, ...session } : session);
      }
      return (
      <DirectSessionIndexList
        renderTrailingActions={renderTrailingActions}
        activeSessionId={activeSessionId}
        addToReviewSucceededLabel={t("addSessionToReviewSucceeded")}
        agentsById={agentsById}
        avatarImageUrlFrom={avatarImageUrlFrom}
        avatarInitials={avatarInitials}
        buildSessionReferencePayload={buildSessionReferencePayload}
        contextMenuSessionId={contextMenuSessionId}
        conversations={sessions.map(sessionToConversationSummary)}
        deleteBusyLabel={t("deleteSessionBusy")}
        editingSessionId={editingSessionId}
        editingSessionTitle={editingSessionTitle}
        formatTime={formatConversationIndexTime}
        groupPanelActive={groupPanelActive}
        isBusyPhase={isBusyPhase}
        lang={lang}
        renamePending={renameSessionMutation.isPending}
        renameSessionId={renameSessionMutation.variables?.sessionId ?? ""}
        resolveModelLabel={resolveModelLabel}
        runtimeRunningSessionIds={runtimeRunningSessionIds}
        sessionComposerErrors={sessionComposerErrors}
        sessionIdsNeedingApproval={sessionIdsNeedingApproval}
        sessionsById={listSessionsById}
        statusLabel={statusLabel}
        t={t}
        onCancelRename={cancelRenameSession}
        onContextMenu={openSessionContextMenu}
        onDragReference={startSessionReferenceDrag}
        onOpen={handleOpenDirectSession}
        onPrefetch={handlePrefetchDirectSession}
        onRenameTitleChange={setEditingSessionTitle}
        onSubmitRename={submitRenameSession}
      />
      );
    };
    const groups = !pinned.length && !timelineGroups.length ? null : (
      <>
        {pinned.length ? (
          <ConversationIndexSection
            count={pinned.length}
            expanded={!railSectionCollapsed.sessionListPinned}
            label={t("sessionListPinnedSection")}
            onToggle={() => toggleRailSection("sessionListPinned")}
          >
            {renderSessionList(pinned)}
          </ConversationIndexSection>
        ) : null}
        {timelineGroups.map((group) => (
          <ConversationIndexSection
            key={group.bucket}
            count={group.sessions.length}
            expanded={!railSectionCollapsed[`sessionListTimeline:${group.bucket}`]}
            label={timelineBucketLabel(group.bucket)}
            onToggle={() => toggleRailSection(`sessionListTimeline:${group.bucket}`)}
          >
            {renderSessionList(group.sessions)}
          </ConversationIndexSection>
        ))}
      </>
    );
    return { groups, renderSessionList };
  })();
  const archivedRailSessions = (() => {
    const fromQuery = archivedSessions.filter((session) => {
      const cached = sessionsById.get(session.id);
      return !cached || isSessionArchived(cached);
    });
    const known = new Set(fromQuery.map((session) => session.id));
    const optimistic = allVisibleSessions.filter((session) => (
      isSessionArchived(session) && !known.has(session.id)
    ));
    return [...fromQuery, ...optimistic];
  })();

  return (
    <>
    <div className={styles.sessionListControlsRow} data-vui="chat-session-list-controls">
      <VStringSelect
        ariaLabel={t("sessionListSortAria")}
        className={styles.sessionListSortSelect}
        value={sessionListPrefs.sortBy}
        onValueChange={(value) => setSessionListPrefs((current) => ({
          ...current,
          sortBy: normalizeSessionListSortBy(value),
        }))}
        options={[
          { value: "updatedAt", label: t("sessionListSortByUpdated") },
          { value: "createdAt", label: t("sessionListSortByCreated") },
        ]}
      />
      {showArchivedSessions ? null : (
        <VIconButton
          type="button"
          data-vui="chat-session-timeline-toggle"
          label={t("sessionListTimelineToggle")}
          tooltip={t("sessionListTimelineToggle")}
          aria-pressed={sessionListPrefs.timelineGrouping}
          onClick={() => setSessionListPrefs((current) => ({
            ...current,
            timelineGrouping: !current.timelineGrouping,
          }))}
          icon={<ListTree size={16} aria-hidden="true" />}
        />
      )}
    </div>
    <ChatConversationIndexPanelContent
      styles={styles}
      loadingLabel={t("loadingSession")}
      sessionsErrorMessage={sessionsErrorMessage}
      sessionComposerSessionsError={sessionComposerErrors.__sessions__}
      sessionsTransientError={sessionsTransientError}
      sessionsBlockingError={sessionsBlockingError}
      conversationIndexLoading={conversationIndexLoading}
      isEmpty={
        showArchivedSessions
          ? !archivedSessionsPending
            && archivedSessions.length === 0
            && allVisibleSessions.every((session) => !isSessionArchived(session) && !(Number(session.pinnedAtMs ?? 0) > 0))
          : filteredConversations.length === 0
            && archiveVisibleAgents.length === 0
            && filteredTeams.length === 0
            && filteredStandaloneGroupConversations.length === 0
            && allVisibleSessions.length === 0
      }
      emptyTitle={showArchivedSessions ? t("noArchivedSessions") : t("noSessionsYet")}
    >
          {sessionListRail.groups}
          {showArchivedSessions ? (
            <ArchivedSessionRail
              sessions={archivedRailSessions}
              totalCount={Math.max(archivedTotalEstimate, archivedRailSessions.length)}
              sortBy={sessionListPrefs.sortBy}
              loading={archivedSessionsPending}
              archivePendingSessionId={
                sessionArchiveMutation.isPending
                  ? String(sessionArchiveMutation.variables?.sessionId || "")
                  : ""
              }
              deletePendingSessionId={
                deleteSessionMutation.isPending
                  ? String(deleteSessionMutation.variables?.sessionId || "")
                  : ""
              }
              deleteAllPending={bulkDeleteSessionsMutation.isPending}
              isBusyPhase={isBusyPhase}
              lang={lang}
              t={t}
              onUnarchive={(session) => sessionArchiveMutation.mutate({
                sessionId: session.id,
                archive: false,
              })}
              onDelete={handleDeleteArchivedSession}
              onDeleteAll={handleDeleteAllArchivedSessions}
              renderSessions={sessionListRail.renderSessionList}
            />
          ) : null}
          {showArchivedSessions ? null : <>
          <AgentConversationDirectory
            activeAgentId={selectedChatAgentId}
            activeSessionId={activeSessionId}
            activeGroupRoomId={activeGroupRoomId}
            agents={archiveVisibleAgents}
            avatarInitials={avatarInitials}
            filterText={directoryFilterText}
            formatTime={formatConversationIndexTime}
            lang={lang}
            resolveModelLabel={resolveModelLabel}
            runtimeRunningSessionIds={runtimeRunningSessionIds}
            sessions={allVisibleSessions}
            sessionIdsNeedingApproval={sessionIdsNeedingApproval}
            statusLabel={statusLabel}
            teams={teams}
            teamRoomsByTeamId={teamRoomsByTeamId}
            onContextMenu={openAgentContextMenu}
            onOpenAgent={(agent) => {
              if (!handleOpenAgent(agent)) {
                handleCreateAgentSession(agent);
              }
            }}
            onOpenGroupRoom={handleOpenGroupRoom}
          />
          {agentContextMenu ? (
            <Suspense fallback={null}>
              <AgentContextMenu
                archivePending={contextMenuAgentArchivePending}
                createPending={createSessionMutation.isPending}
                renamePending={renameAgentMutation.isPending}
                lang={lang}
                state={agentContextMenu}
                onArchive={handleArchiveAgent}
                onCreateSession={handleCreateAgentSession}
                onOpenConfig={handleOpenAgentConfig}
                onOpenLatest={handleOpenAgentLatestSession}
                onRename={handleRenameAgent}
                onDismiss={() => setAgentContextMenu(null)}
              />
            </Suspense>
          ) : null}
          {agentRenameDraft ? (
            <Suspense fallback={null}>
              <AgentRenameDialog
                draft={agentRenameDraft}
                lang={lang}
                pending={renameAgentMutation.isPending}
                onCancel={cancelAgentRename}
                onChange={setAgentRenameDraftName}
                onSubmit={submitAgentRename}
              />
            </Suspense>
          ) : null}
          {sessionBulkNotice ? (
            <div className={styles.panelNotice} role="status">{sessionBulkNotice.text}</div>
          ) : null}
          <SessionBulkOperationsPanel
            copy={sessionBulkCopy}
            selectedCount={selectedBulkSessions.length}
            visibleCount={visibleDirectSessionIds.length}
            allVisibleSelected={allVisibleSessionsSelected}
            pending={bulkSessionPending}
            onSelectVisible={selectVisibleBulkSessions}
            onClearSelection={clearBulkSessions}
            onRemove={() => { void bulkRemoveSessions(); }}
          />
          <ConversationIndexTree
            activeGroupRoomId={activeGroupRoomId}
            activeSessionId={activeSessionId}
            addToReviewSucceededLabel={t("addSessionToReviewSucceeded")}
            agentsById={agentsById}
            avatarImageUrlFrom={avatarImageUrlFrom}
            avatarInitials={avatarInitials}
            buildSessionReferencePayload={buildSessionReferencePayload}
            collapsedConversationGroups={collapsedConversationGroups}
            contextMenuSessionId={contextMenuSessionId}
            conversationGroupLabel={conversationGroupLabel}
            deleteBusyLabel={t("deleteSessionBusy")}
            editingSessionId={editingSessionId}
            editingSessionTitle={editingSessionTitle}
            filteredConversationsCount={groupedGroupConversationCount}
            filteredStandaloneGroupConversations={filteredStandaloneGroupConversations}
            filteredTeams={filteredTeams}
            formatTime={formatConversationIndexTime}
            groupPanelActive={groupPanelActive}
            groupedConversations={groupedGroupConversations}
            isBusyPhase={isBusyPhase}
            lang={lang}
            renamePending={renameSessionMutation.isPending}
            renameSessionId={renameSessionMutation.variables?.sessionId ?? ""}
            resolveModelLabel={resolveModelLabel}
            runtimeRunningSessionIds={runtimeRunningSessionIds}
            searchHasTerm={searchHasTerm}
            sessionComposerErrors={sessionComposerErrors}
            sessionIdsNeedingApproval={sessionIdsNeedingApproval}
            sessionsById={sessionsById}
            teams={teams}
            statusLabel={statusLabel}
            t={t}
            onCancelRename={cancelRenameSession}
            onContextMenu={openSessionContextMenu}
            onDragReference={startSessionReferenceDrag}
            onOpenDirectSession={handleOpenDirectSession}
            onPrefetchDirectSession={handlePrefetchDirectSession}
            onOpenGroupRoom={handleOpenGroupRoom}
            onRenameTitleChange={setEditingSessionTitle}
            onSubmitRename={submitRenameSession}
            onToggleConversationGroup={toggleConversationGroup}
            bulkSelectionEnabled
            selectedBulkSessionIds={selectedBulkSessionIds}
            bulkSelectLabel={lang === "zh" ? "选择会话" : "Select session"}
            onToggleBulk={toggleBulkSession}
          />
          </>}
          {sessionContextMenu && contextMenuSession ? (
            <Suspense fallback={null}>
              <SessionContextMenu
                addToReviewDisabled={contextMenuAddToReviewDisabled}
                addToReviewPending={contextMenuAddToReviewPending}
                pinDisabled={pinSessionMutation.isPending}
                pinPending={
                  pinSessionMutation.isPending
                  && pinSessionMutation.variables?.sessionId === contextMenuSession.id
                }
                clearHistoryDisabled={contextMenuClearHistoryDisabled}
                clearHistoryPending={contextMenuClearHistoryPending}
                clearHistoryVisible={contextMenuClearHistoryVisible}
                deleteDisabled={contextMenuDeleteDisabled}
                lang={lang}
                position={sessionContextMenu}
                session={contextMenuSession}
                t={t}
                archiveDisabled={sessionArchiveMutation.isPending}
                archivePending={
                  sessionArchiveMutation.isPending
                  && sessionArchiveMutation.variables?.sessionId === contextMenuSession.id
                }
                onAddToReview={handleAddSessionToReview}
                onArchive={handleArchiveSession}
                onTogglePin={handleTogglePinSession}
                onClearHistory={handleClearSessionHistory}
                onDelete={handleDeleteSession}
                onOpenAgentConfig={openSessionAgentConfig}
                onOpenReportLibrary={onOpenReportLibrary}
                onRename={beginRenameSession}
                onDismiss={() => setSessionContextMenu(null)}
              />
            </Suspense>
          ) : null}
    </ChatConversationIndexPanelContent>
    </>
  );
}
