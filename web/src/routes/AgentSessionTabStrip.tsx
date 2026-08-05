import { Bot, Check, LoaderCircle, Plus, SquareTerminal, X } from "lucide-react";
import type { DragEvent, KeyboardEvent, MouseEvent as ReactMouseEvent } from "react";

import type { AgentInstance, SessionReferenceAttachment, SessionSummary } from "../api/types";
import { VButton, VIconButton, VNativeInput } from "../components/vui";
import type { TranslationKey } from "../i18n/dictionary";
import { sessionAgentDisplayInfo } from "./agentDisplay";
import {
  resolveSessionActivityTone,
  sessionActivityLabel,
  type SessionActivityTone,
} from "./sessionActivityIndicator";
import styles from "./AgentSessionTabStrip.styles";
import { isBusyPhase } from "./chat/chatCodingRouteViewModel";

export type CliAgentRunTab = {
  id: string;
  title: string;
  summary: string;
  status: string;
  agentType: string;
  mode: string;
};

/**
 * Tab activity indicators (not selection):
 * - green spinner  running  = 会话进行中
 * - yellow spinner approval = 需要审批
 * - red light      error    = 出错
 * - blue light     completed = 已完成（未读）
 * - none           idle / already read
 * Selection is a separate border/ring on the active tab.
 */
export type AgentSessionStatusTone = SessionActivityTone;

export function agentSessionStatusTone(
  status: string,
  options?: {
    needsApproval?: boolean;
    isRuntimeRunning?: boolean;
    session?: Pick<
      SessionSummary,
      | "id"
      | "childStatus"
      | "currentPhase"
      | "status"
      | "lastTurnStatus"
      | "sessionKind"
      | "updatedAt"
      | "lastActive"
      | "agentInboxPendingCount"
    >;
    isActive?: boolean;
  },
): AgentSessionStatusTone {
  if (options?.session) {
    return resolveSessionActivityTone(
      {
        ...options.session,
        status: options.session.status || status,
        currentPhase: options.session.currentPhase || status,
        childStatus: options.session.childStatus || status,
      },
      {
        needsApproval: options.needsApproval,
        isRuntimeRunning: options.isRuntimeRunning,
        isActive: options.isActive,
      },
    );
  }
  return resolveSessionActivityTone(
    { status, currentPhase: status, childStatus: status },
    {
      needsApproval: options?.needsApproval,
      isRuntimeRunning: options?.isRuntimeRunning,
      isActive: options?.isActive,
    },
  );
}

function agentSessionStatusIndicatorClassName(tone: AgentSessionStatusTone) {
  return [
    styles.agentSessionTabStatusIndicator,
    tone === "running" ? styles.agentSessionTabStatusRunning : "",
    tone === "error" ? styles.agentSessionTabStatusError : "",
    tone === "approval" ? styles.agentSessionTabStatusApproval : "",
    tone === "completed" ? styles.agentSessionTabStatusCompleted : "",
  ].filter(Boolean).join(" ");
}

/** Fixed-width status cell: always rendered so tab width/close alignment stay stable. */
function renderAgentSessionStatusSlot(tone: AgentSessionStatusTone) {
  return (
    <span className={styles.agentSessionTabStatusSlot} aria-hidden="true" data-session-tab-status-slot>
      {tone === "none" ? null : (
        <span className={styles.agentSessionTabStatus}>
          <span className={agentSessionStatusIndicatorClassName(tone)}>
            {tone === "running" || tone === "approval" ? (
              <LoaderCircle size={11} aria-hidden="true" className={styles.agentSessionTabStatusSpinner} />
            ) : null}
          </span>
        </span>
      )}
    </span>
  );
}

export function agentSessionStatusShortLabel(tone: AgentSessionStatusTone, lang: "zh" | "en") {
  return sessionActivityLabel(tone, lang);
}

export type AgentSessionTabStripProps = {
  activeSessionId: string | null;
  activeCliAgentRunId?: string;
  agentsById: Map<string, AgentInstance>;
  buildSessionReferencePayload: (
    session: SessionSummary,
    displayName: string,
    summary: string,
  ) => SessionReferenceAttachment;
  contextMenuSessionId: string;
  editingSessionId: string | null;
  editingSessionTitle: string;
  lang: "zh" | "en";
  renamePending: boolean;
  renameSessionId: string;
  resolveModelLabel: (modelId: string) => string | undefined;
  cliAgentRuns?: CliAgentRunTab[];
  createPending?: boolean;
  createDisabled?: boolean;
  /** When set, only that session's close control is pending (not a global lock). */
  deletePendingSessionId?: string;
  /** @deprecated use deletePendingSessionId — global true freezes every tab close. */
  deletePending?: boolean;
  sessions: SessionSummary[];
  /** Session ids with an active runtime chat_turn (green spinner). */
  runtimeRunningSessionIds?: readonly string[];
  /** Session ids waiting on tool/permission approval (yellow spinner). */
  sessionIdsNeedingApproval?: readonly string[];
  statusLabel: (status: string) => string;
  t: (key: TranslationKey) => string;
  workspaceActiveTab: string;
  onCancelRename: () => void;
  onContextMenu: (event: ReactMouseEvent<HTMLElement>, session: SessionSummary) => void;
  onDragReference: (event: DragEvent<HTMLElement>, reference: SessionReferenceAttachment) => void;
  onOpenDirectSession: (sessionId: string) => void;
  onPrefetchDirectSession?: (sessionId: string) => void;
  onOpenCliAgentRun?: (runId: string) => void;
  onCloseCliAgentRun?: (runId: string) => void;
  onCreateSession: () => void;
  onDeleteSession: (session: SessionSummary) => void;
  onRenameTitleChange: (title: string) => void;
  onSetActiveTab: (sessionId: string, tab: "agent") => void;
  onSubmitRename: (session: SessionSummary, options?: { reason?: "blur" | "explicit" }) => void;
};

function agentSessionTabElementId(kind: "session" | "cli", id: string) {
  return `agent-session-tab-${kind}-${encodeURIComponent(id)}`;
}

export function AgentSessionTabStrip({
  activeSessionId,
  activeCliAgentRunId = "",
  agentsById,
  buildSessionReferencePayload,
  contextMenuSessionId,
  editingSessionId,
  editingSessionTitle,
  lang,
  renamePending,
  renameSessionId,
  resolveModelLabel,
  cliAgentRuns = [],
  createPending = false,
  createDisabled = false,
  deletePendingSessionId = "",
  deletePending = false,
  sessions,
  runtimeRunningSessionIds = [],
  sessionIdsNeedingApproval = [],
  statusLabel: _statusLabel,
  t,
  workspaceActiveTab,
  onCancelRename,
  onContextMenu,
  onDragReference,
  onOpenDirectSession,
  onPrefetchDirectSession,
  onOpenCliAgentRun,
  onCloseCliAgentRun,
  onCreateSession,
  onDeleteSession,
  onRenameTitleChange,
  onSetActiveTab,
  onSubmitRename,
}: AgentSessionTabStripProps) {
  const approvalSessionIds = new Set(
    sessionIdsNeedingApproval.map((id) => String(id || "").trim()).filter(Boolean),
  );
  const runtimeSessionIds = new Set(
    runtimeRunningSessionIds.map((id) => String(id || "").trim()).filter(Boolean),
  );
  const navigationTabs = [
    ...sessions.map((session) => ({ kind: "session" as const, id: session.id })),
    ...cliAgentRuns.map((run) => ({ kind: "cli" as const, id: run.id })),
  ];
  const keyboardTabs = navigationTabs.filter((tab) => (
    tab.kind !== "session" || tab.id !== editingSessionId
  ));
  const activeKeyboardTabIndex = Math.max(
    0,
    keyboardTabs.findIndex((tab) => (
      activeCliAgentRunId
        ? tab.kind === "cli" && tab.id === activeCliAgentRunId
        : tab.kind === "session" && tab.id === activeSessionId
    )),
  );
  const handleTabKeyDown = (
    event: KeyboardEvent<HTMLButtonElement>,
    tabIndex: number,
  ) => {
    let nextIndex: number | null = null;
    if (event.key === "ArrowRight") {
      nextIndex = (tabIndex + 1) % keyboardTabs.length;
    } else if (event.key === "ArrowLeft") {
      nextIndex = (tabIndex - 1 + keyboardTabs.length) % keyboardTabs.length;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = keyboardTabs.length - 1;
    }
    if (nextIndex === null || nextIndex < 0) {
      return;
    }
    const nextTab = keyboardTabs[nextIndex];
    if (!nextTab) {
      return;
    }
    event.preventDefault();
    if (nextTab.kind === "session") {
      if (activeSessionId === nextTab.id) {
        onSetActiveTab(nextTab.id, "agent");
      } else {
        onOpenDirectSession(nextTab.id);
      }
    } else {
      onOpenCliAgentRun?.(nextTab.id);
    }
    requestAnimationFrame(() => {
      document.getElementById(agentSessionTabElementId(nextTab.kind, nextTab.id))?.focus();
    });
  };

  return (
    <div className={styles.agentSessionTabRail}>
      <div
        className={styles.agentSessionTabGroup}
        role={keyboardTabs.length > 0 ? "tablist" : undefined}
        aria-label={keyboardTabs.length > 0 ? (lang === "zh" ? "Agent 会话" : "Agent sessions") : undefined}
      >
      {sessions.map((session) => {
        const sessionAgent = session.agentId ? agentsById.get(session.agentId) : undefined;
        const sessionDisplay = sessionAgentDisplayInfo(session, sessionAgent, lang, resolveModelLabel);
        const sessionStatus = session.childStatus || session.status || session.currentPhase;
        const needsApproval = approvalSessionIds.has(session.id);
        const isRuntimeRunning = runtimeSessionIds.has(session.id);
        const tabActive = activeSessionId === session.id && workspaceActiveTab === "agent" && !activeCliAgentRunId;
        const statusTone = agentSessionStatusTone(String(sessionStatus || ""), {
          needsApproval,
          isRuntimeRunning,
          session,
          isActive: tabActive,
        });
        const statusShortLabel = agentSessionStatusShortLabel(statusTone, lang);
        const sessionTitle =
          session.title
          || sessionDisplay.name
          || t("agentSession");
        const sessionSummary =
          session.taskSummary
          || session.resultCard?.summary
          || sessionDisplay.modelLabel
          || "";
        const sessionHoverTitle = [sessionTitle, statusShortLabel, sessionSummary, sessionDisplay.modelLabel]
          .filter(Boolean)
          .join(" · ");
        const tabContextTarget = contextMenuSessionId === session.id;
        const tabEditing = editingSessionId === session.id;
        const keyboardIndex = keyboardTabs.findIndex((tab) => tab.kind === "session" && tab.id === session.id);
        const sessionDeletePending = Boolean(
          deletePending
          || (deletePendingSessionId && deletePendingSessionId === session.id),
        );
        const deleteDisabled = isBusyPhase(session.currentPhase || session.status) || sessionDeletePending;
        const tabClassName = [
          styles.agentSessionTab,
          styles.agentSessionTabRoot,
          tabActive ? styles.agentSessionTabActive : "",
          tabContextTarget && !tabActive ? styles.agentSessionTabContextTarget : "",
          tabEditing ? styles.agentSessionTabEditing : "",
        ].filter(Boolean).join(" ");
        const tabMainActionClassName = [
          styles.agentSessionTabMainAction,
          tabActive ? styles.agentSessionTabMainActionActive : "",
          tabContextTarget && !tabActive ? styles.agentSessionTabMainActionContextTarget : "",
        ].filter(Boolean).join(" ");
        if (tabEditing) {
          const sessionRenamePending = renamePending && renameSessionId === session.id;
          return (
            <div
              key={session.id}
              className={tabClassName}
              role="presentation"
              data-agent-session-tab-container
              onContextMenu={(event) => onContextMenu(event, session)}
            >
              <span className={styles.agentSessionTabIcon} aria-hidden="true">
                <Bot size={14} />
              </span>
              <VNativeInput
                className={styles.agentSessionTabTitleInput}
                value={editingSessionTitle}
                maxLength={120}
                autoFocus
                placeholder={lang === "zh" ? "会话名称" : "Session name"}
                onChange={(event) => onRenameTitleChange(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    onSubmitRename(session, { reason: "explicit" });
                  }
                  if (event.key === "Escape") {
                    event.preventDefault();
                    onCancelRename();
                  }
                }}
                onBlur={(event) => {
                  const nextFocus = event.relatedTarget;
                  if (nextFocus instanceof Node && event.currentTarget.closest("[data-agent-session-tab-container]")?.contains(nextFocus)) {
                    return;
                  }
                  onSubmitRename(session, { reason: "blur" });
                }}
                aria-label={t("renameSession")}
              />
              <span className={styles.agentSessionTabEditActions}>
                <VIconButton
                  type="button"
                  variant="ghost"
                  className={styles.agentSessionTabEditButton}
                  onPress={() => onSubmitRename(session, { reason: "explicit" })}
                  isDisabled={sessionRenamePending}
                  title={t("saveSessionName")}
                  label={`${t("saveSessionName")} ${sessionTitle}`}
                  icon={<Check size={13} />}
                />
                <VIconButton
                  type="button"
                  variant="ghost"
                  className={styles.agentSessionTabEditButton}
                  onPress={onCancelRename}
                  isDisabled={sessionRenamePending}
                  title={t("cancelRenameSession")}
                  label={t("cancelRenameSession")}
                  icon={<X size={13} />}
                />
              </span>
            </div>
          );
        }
        const dragReferenceProps = {
          draggable: true,
          onDragStart: (event: DragEvent<HTMLDivElement>) =>
            onDragReference(
              event,
              buildSessionReferencePayload(session, sessionDisplay.name, sessionSummary),
            ),
        };
        return (
          <div
            key={session.id}
            className={`${tabClassName} ${styles.agentSessionTabClosable}`}
            role="presentation"
            data-agent-session-tab-container
            {...dragReferenceProps}
            onContextMenu={(event) => onContextMenu(event, session)}
          >
            <VButton
              type="button"
              contentLayout="plain"
              className={tabMainActionClassName}
              id={agentSessionTabElementId("session", session.id)}
              role="tab"
              aria-selected={tabActive}
              aria-current={tabActive ? "true" : undefined}
              tabIndex={keyboardIndex === activeKeyboardTabIndex ? 0 : -1}
              onKeyDown={(event) => handleTabKeyDown(event, keyboardIndex)}
              data-session-tab-active={tabActive ? "true" : "false"}
              onPointerEnter={() => onPrefetchDirectSession?.(session.id)}
              onFocus={() => onPrefetchDirectSession?.(session.id)}
              onPress={() => {
                if (activeSessionId === session.id) {
                  onSetActiveTab(session.id, "agent");
                  return;
                }
                onOpenDirectSession(session.id);
              }}
              title={sessionHoverTitle}
              aria-label={
                tabActive
                  ? (statusShortLabel
                    ? `${lang === "zh" ? "当前会话" : "Current session"}: ${sessionTitle} · ${statusShortLabel}`
                    : `${lang === "zh" ? "当前会话" : "Current session"}: ${sessionTitle}`)
                  : (statusShortLabel ? `${sessionTitle} · ${statusShortLabel}` : sessionTitle)
              }
            >
              <span
                className={[
                  styles.agentSessionTabIcon,
                  tabActive ? styles.agentSessionTabIconActive : "",
                ].filter(Boolean).join(" ")}
                aria-hidden="true"
              >
                <Bot size={14} />
              </span>
              <span className={styles.agentSessionTabTitleBlock}>
                <span
                  className={[
                    styles.agentSessionTabTitle,
                    tabActive ? styles.agentSessionTabTitleActive : "",
                  ].filter(Boolean).join(" ")}
                >{sessionTitle}</span>
              </span>
              {renderAgentSessionStatusSlot(statusTone)}
            </VButton>
            <VIconButton
              type="button"
              variant="ghost"
              className={styles.agentSessionTabCloseButton}
              onClick={(event) => {
                event.stopPropagation();
                onDeleteSession(session);
              }}
              isDisabled={deleteDisabled}
              title={deleteDisabled ? t("deleteSessionBusy") : t("deleteSession")}
              label={`${deleteDisabled ? t("deleteSessionBusy") : t("deleteSession")} ${sessionTitle}`}
              icon={<X size={13} />}
            />
          </div>
        );
      })}
      {cliAgentRuns.map((run) => {
        const tabActive = activeCliAgentRunId === run.id;
        const statusTone = agentSessionStatusTone(run.status);
        const statusShortLabel = agentSessionStatusShortLabel(statusTone, lang);
        const title = [run.title, statusShortLabel, run.summary].filter(Boolean).join(" · ");
        const tabMainActionClassName = [
          styles.agentSessionTabMainAction,
          tabActive ? styles.agentSessionTabMainActionActive : "",
        ].filter(Boolean).join(" ");
        const tabClassName = [
          styles.agentSessionTab,
          styles.agentSessionTabCli,
          tabActive ? styles.agentSessionTabActive : "",
        ].filter(Boolean).join(" ");
        const keyboardIndex = keyboardTabs.findIndex((tab) => tab.kind === "cli" && tab.id === run.id);
        return (
          <div
            key={run.id}
            className={`${tabClassName} ${styles.agentSessionTabClosable}`}
            role="presentation"
            data-agent-session-tab-container
          >
            <VButton
              type="button"
              contentLayout="plain"
              className={tabMainActionClassName}
              id={agentSessionTabElementId("cli", run.id)}
              role="tab"
              aria-selected={tabActive}
              aria-current={tabActive ? "true" : undefined}
              tabIndex={keyboardIndex === activeKeyboardTabIndex ? 0 : -1}
              onKeyDown={(event) => handleTabKeyDown(event, keyboardIndex)}
              data-session-tab-active={tabActive ? "true" : "false"}
              onPress={() => onOpenCliAgentRun?.(run.id)}
              title={title}
              aria-label={
                tabActive
                  ? (statusShortLabel
                    ? `${lang === "zh" ? "当前终端" : "Current terminal"}: ${run.title} · ${statusShortLabel}`
                    : `${lang === "zh" ? "当前终端" : "Current terminal"}: ${run.title}`)
                  : (statusShortLabel ? `${run.title} · ${statusShortLabel}` : run.title)
              }
            >
              <span
                className={[
                  styles.agentSessionTabIcon,
                  tabActive ? styles.agentSessionTabIconActive : "",
                ].filter(Boolean).join(" ")}
                aria-hidden="true"
              >
                <SquareTerminal size={14} />
              </span>
              <span className={styles.agentSessionTabTitleBlock}>
                <span
                  className={[
                    styles.agentSessionTabTitle,
                    tabActive ? styles.agentSessionTabTitleActive : "",
                  ].filter(Boolean).join(" ")}
                >{run.title}</span>
              </span>
              {renderAgentSessionStatusSlot(statusTone)}
            </VButton>
            <VIconButton
              type="button"
              variant="ghost"
              className={styles.agentSessionTabCloseButton}
              onClick={(event) => {
                event.stopPropagation();
                onCloseCliAgentRun?.(run.id);
              }}
              title={lang === "zh" ? "关闭终端页" : "Close terminal tab"}
              label={`${lang === "zh" ? "关闭终端页" : "Close terminal tab"} ${run.title}`}
              icon={<X size={13} />}
            />
          </div>
        );
      })}
      </div>
      {editingSessionId ? null : (
        <VIconButton
          type="button"
          variant="ghost"
          className={styles.agentSessionTabCreateButton}
          onPress={onCreateSession}
          isDisabled={createPending || createDisabled}
          title={lang === "zh" ? "在当前 Agent 下新建会话" : "New session for current Agent"}
          label={lang === "zh" ? "在当前 Agent 下新建会话" : "New session for current Agent"}
          icon={<Plus size={14} />}
        />
      )}
    </div>
  );
}
