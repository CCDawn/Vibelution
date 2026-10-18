/**
 * Chat center tab strip: companion header, session tabs, file tabs, export.
 * The workbench keeps layout state and passes it in; this module owns the strip JSX.
 */
import { List, PanelLeftOpen } from "lucide-react";
import { lazy, useMemo, type Dispatch, type SetStateAction } from "react";

import type { AgentInstance, ConversationMessage, SessionSummary, Team, VirtualHumanCompanion } from "../../api/types";
import { ConversationShareExportButton } from "../../components/conversation/ConversationShareExportButton";
import { ConversationTodoProgressButton } from "../../components/conversation/ConversationTodoProgressButton";
import { deriveSessionTodoChecklist } from "../../components/conversation/conversationTodoChecklistModel";
import { VIconButton } from "../../components/vui";
import type { TranslationKey } from "../../i18n/dictionary";
import { AgentSessionTabStrip, type AgentSessionTabStripProps, type SessionBarRailTab } from "../AgentSessionTabStrip";
import { CompanionConversationHeader } from "../companions/CompanionConversationHeader";
import styles from "../ChatCodingRoute.styles";
import { ChatCenterTabStrip } from "./ChatCenterTabStrip";
import { cliAgentRunTabId, type CliAgentRunView } from "./cliAgentRunModel";
import type { PaneDockPayload, SessionBarDockChip } from "./chatPaneDock";

const ChatFileWorkspaceTabs = lazy(() =>
  import("./ChatFileWorkspaceTabs").then((module) => ({ default: module.ChatFileWorkspaceTabs })),
);

export type ChatCodingCenterTabsProps = {
  lang: "zh" | "en";
  chatReturnTarget: string | null;
  chatReturnLabel: string;
  groupPanelActive: boolean;
  projectBusActive: boolean;
  financeSurface: boolean;
  verifiedCompanionMode: boolean;
  selectedChatAgentId: string;
  agentSessionTabs: SessionSummary[];
  cliAgentRunTabs: CliAgentRunView[];
  activeCompanion: VirtualHumanCompanion | null;
  leftOverlayVisible: boolean;
  rightOverlayVisible: boolean;
  conversationIndexCollapsed: boolean;
  setLeftRailCollapsed: Dispatch<SetStateAction<boolean>>;
  conversationWorkspaceTab: string;
  sessionBrowserVisible: boolean;
  setSessionBrowserOpen: Dispatch<SetStateAction<boolean>>;
  headerExportVisible: boolean;
  conversationModel: { sessionId: string; messages: ConversationMessage[] } | null;
  conversationIndexOverlayOpen: boolean;
  ordinaryChangeRail: boolean;
  changeRailVisible: boolean;
  statusRailOverlayOpen: boolean;
  toggleChangeRail: () => void;
  setResponsiveOverlayPane: Dispatch<SetStateAction<"left" | "right" | null>>;
  activeSessionId: string | null | undefined;
  setActiveTab: (sessionId: string, tabId: string) => void;
  activeCliAgentRunId: string;
  agentsById: Map<string, AgentInstance>;
  buildSessionReferencePayload: AgentSessionTabStripProps["buildSessionReferencePayload"];
  contextMenuSessionId: string;
  createSessionPending: boolean;
  deleteSessionPending: boolean;
  pendingDeleteSessionId: string;
  editingSessionId: string | null;
  editingSessionTitle: string;
  renamePending: boolean;
  renameSessionId: string;
  resolveModelLabel: AgentSessionTabStripProps["resolveModelLabel"];
  teams: Team[];
  runtimeRunningSessionIds: readonly string[];
  sessionIdsNeedingApproval: readonly string[];
  statusLabel: (status: string) => string;
  t: (key: TranslationKey) => string;
  onCancelRename: () => void;
  onContextMenu: AgentSessionTabStripProps["onContextMenu"];
  onDragReference: AgentSessionTabStripProps["onDragReference"];
  closeCliAgentRun: (run: CliAgentRunView) => Promise<void>;
  onCreateSession: () => void;
  onDeleteSession: AgentSessionTabStripProps["onDeleteSession"];
  onOpenDirectSession: (sessionId: string) => void;
  onPrefetchDirectSession?: (sessionId: string) => void;
  onRenameTitleChange: (title: string) => void;
  onSubmitRename: AgentSessionTabStripProps["onSubmitRename"];
  workspace: { activeTab: string; openTabs: string[] };
  closePreviewTab: (sessionId: string, path: string) => void;
  paneDockChips?: SessionBarDockChip[];
  onPaneDockChipSelect?: (chip: SessionBarDockChip) => void;
  onPaneDockChipClose?: (chip: SessionBarDockChip) => void;
  onPaneDockDrop?: (payload: PaneDockPayload) => void;
  onSessionTabSelected?: () => void;
  railRowTabs?: SessionBarRailTab[];
  onRailRowTabSelect?: (tabId: string) => void;
  onRailRowTabClose?: (tabId: string) => void;
};

export function ChatCodingCenterTabs({
  lang,
  chatReturnTarget,
  chatReturnLabel,
  groupPanelActive,
  projectBusActive,
  financeSurface,
  verifiedCompanionMode,
  selectedChatAgentId,
  agentSessionTabs,
  cliAgentRunTabs,
  activeCompanion,
  leftOverlayVisible,
  rightOverlayVisible,
  conversationIndexCollapsed,
  setLeftRailCollapsed,
  conversationWorkspaceTab,
  sessionBrowserVisible,
  setSessionBrowserOpen,
  headerExportVisible,
  conversationModel,
  conversationIndexOverlayOpen,
  ordinaryChangeRail,
  changeRailVisible,
  statusRailOverlayOpen,
  toggleChangeRail,
  setResponsiveOverlayPane,
  activeSessionId,
  setActiveTab,
  activeCliAgentRunId,
  agentsById,
  buildSessionReferencePayload,
  contextMenuSessionId,
  createSessionPending,
  deleteSessionPending,
  pendingDeleteSessionId,
  editingSessionId,
  editingSessionTitle,
  renamePending,
  renameSessionId,
  resolveModelLabel,
  teams,
  runtimeRunningSessionIds,
  sessionIdsNeedingApproval,
  statusLabel,
  t,
  onCancelRename,
  onContextMenu,
  onDragReference,
  closeCliAgentRun,
  onCreateSession,
  onDeleteSession,
  onOpenDirectSession,
  onPrefetchDirectSession,
  onRenameTitleChange,
  onSubmitRename,
  workspace,
  closePreviewTab,
  paneDockChips = [],
  onPaneDockChipSelect,
  onPaneDockChipClose,
  onPaneDockDrop,
  onSessionTabSelected,
  railRowTabs = [],
  onRailRowTabSelect,
  onRailRowTabClose,
}: ChatCodingCenterTabsProps) {
  const taskPlan = useMemo(() => (
    ordinaryChangeRail && !financeSurface && !verifiedCompanionMode && !groupPanelActive
      && activeSessionId && conversationModel?.sessionId === activeSessionId
      ? deriveSessionTodoChecklist(conversationModel.messages)
      : undefined
  ), [ordinaryChangeRail, financeSurface, verifiedCompanionMode, groupPanelActive, activeSessionId, conversationModel]);
  return (
    <ChatCenterTabStrip
      styles={styles}
      lang={lang}
      agentSessionLabel={t("agentSession")}
      chatReturnTarget={chatReturnTarget}
      chatReturnLabel={chatReturnLabel}
      groupPanelActive={groupPanelActive}
      projectBusActive={projectBusActive}
      showSessionTabs={!financeSurface && !verifiedCompanionMode && Boolean(selectedChatAgentId || agentSessionTabs.length > 0 || cliAgentRunTabs.length > 0 || railRowTabs.length > 0)}
      showAgentFallbackTab={!financeSurface && !verifiedCompanionMode}
      companionHeader={verifiedCompanionMode && activeCompanion ? (
        <CompanionConversationHeader companion={activeCompanion} lang={lang} />
      ) : null}
      conversationIndexControl={!financeSurface && !verifiedCompanionMode && leftOverlayVisible && conversationIndexCollapsed ? (
        <VIconButton
          tooltip=""
          id="chat-conversation-index-toggle"
          className={styles.conversationIndexToggle}
          label={lang === "zh" ? "展开会话列" : "Expand conversation column"}
          aria-expanded={false}
          aria-controls="chat-conversation-index-pane"
          icon={<PanelLeftOpen size={16} aria-hidden="true" />}
          onClick={() => {
            setLeftRailCollapsed(false);
            window.requestAnimationFrame(() => document.getElementById("chat-conversation-index-collapse")?.focus());
          }}
        />
      ) : null}
      workspaceActiveTab={conversationWorkspaceTab}
      sessionBrowserControl={!financeSurface && !verifiedCompanionMode && !groupPanelActive ? (
        <VIconButton
          label={lang === "zh" ? "浏览会话" : "Browse sessions"}
          icon={<List size={16} strokeWidth={1.5} aria-hidden="true" />}
          className={sessionBrowserVisible ? `${styles.toolbarIconButton} ${styles.tabActive}` : styles.toolbarIconButton}
          aria-pressed={sessionBrowserVisible}
          onPress={() => setSessionBrowserOpen(current => !current)}
        />
      ) : null}
      sessionActionsControl={headerExportVisible && conversationModel ? <ConversationShareExportButton
        key={conversationModel.sessionId}
        sessionId={conversationModel.sessionId}
        messages={conversationModel.messages}
        language={lang}
        presentation="menu"
        isDisabled={conversationModel.messages.length === 0}
      /> : undefined}
      taskProgressControl={taskPlan && activeSessionId ? (
        <ConversationTodoProgressButton
          key={activeSessionId}
          plan={taskPlan}
          lang={lang}
        />
      ) : undefined}
      leftOverlayVisible={leftOverlayVisible}
      rightOverlayVisible={rightOverlayVisible}
      conversationIndexOverlayOpen={conversationIndexOverlayOpen}
      statusRailAvailable={verifiedCompanionMode}
      rightRailLabel={ordinaryChangeRail && !sessionBrowserVisible ? (lang === "zh" ? "侧栏" : "Side") : undefined}
      rightRailOpen={ordinaryChangeRail ? changeRailVisible : statusRailOverlayOpen}
      statusRailOverlayOpen={statusRailOverlayOpen}
      onActivateAgentFallbackTab={() => {
        setSessionBrowserOpen(false);
        activeSessionId && setActiveTab(activeSessionId, "agent");
      }}
      onToggleLeftOverlay={() => setResponsiveOverlayPane((current) => current === "left" ? null : "left")}
      onToggleRightOverlay={toggleChangeRail}
      sessionTabs={(
        <AgentSessionTabStrip
          activeSessionId={groupPanelActive ? null : (activeSessionId ?? null)}
          activeCliAgentRunId={activeCliAgentRunId}
          agentsById={agentsById}
          buildSessionReferencePayload={buildSessionReferencePayload}
          contextMenuSessionId={contextMenuSessionId}
          cliAgentRuns={cliAgentRunTabs}
          createPending={createSessionPending}
          createDisabled={!selectedChatAgentId}
          deletePendingSessionId={deleteSessionPending ? pendingDeleteSessionId : ""}
          editingSessionId={editingSessionId}
          editingSessionTitle={editingSessionTitle}
          lang={lang}
          renamePending={renamePending}
          renameSessionId={renameSessionId}
          resolveModelLabel={resolveModelLabel}
          sessions={agentSessionTabs}
          teams={teams}
          runtimeRunningSessionIds={runtimeRunningSessionIds}
          sessionIdsNeedingApproval={sessionIdsNeedingApproval}
          statusLabel={statusLabel}
          t={t}
          workspaceActiveTab={conversationWorkspaceTab}
          onCancelRename={onCancelRename}
          onContextMenu={onContextMenu}
          onDragReference={onDragReference}
          onOpenCliAgentRun={(runId) => {
            setSessionBrowserOpen(false);
            if (activeSessionId) {
              setActiveTab(activeSessionId, cliAgentRunTabId(runId));
            }
          }}
          onCloseCliAgentRun={(runId) => {
            const run = cliAgentRunTabs.find((item) => item.id === runId);
            if (run) {
              void closeCliAgentRun(run);
            }
          }}
          onCreateSession={onCreateSession}
          onDeleteSession={onDeleteSession}
          onOpenDirectSession={onOpenDirectSession}
          onPrefetchDirectSession={onPrefetchDirectSession}
          onRenameTitleChange={onRenameTitleChange}
          onSetActiveTab={(sessionId, tab) => {
            onSessionTabSelected?.();
            setSessionBrowserOpen(false);
            setActiveTab(sessionId, tab);
          }}
          onSubmitRename={onSubmitRename}
          paneDockChips={paneDockChips}
          onPaneDockChipSelect={onPaneDockChipSelect}
          onPaneDockChipClose={onPaneDockChipClose}
          onPaneDockDrop={onPaneDockDrop}
          railRowTabs={railRowTabs}
          onRailRowTabSelect={onRailRowTabSelect}
          onRailRowTabClose={onRailRowTabClose}
        />
      )}
      fileTabs={(
        <ChatFileWorkspaceTabs
          activeTab={workspace.activeTab}
          closePreviewTabLabel={t("closePreviewTab")}
          hidden={groupPanelActive}
          openTabs={workspace.openTabs}
          onCloseTab={(tabPath) => {
            activeSessionId && closePreviewTab(activeSessionId, tabPath);
          }}
          onOpenTab={(tabPath) => {
            setSessionBrowserOpen(false);
            activeSessionId && setActiveTab(activeSessionId, tabPath);
          }}
        />
      )}
    />
  );
}
