import { Bot, Check, LoaderCircle, SquareTerminal, X } from "lucide-react";
import type { DragEvent, MouseEvent as ReactMouseEvent } from "react";

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
  onOpenCliAgentRun?: (runId: string) => void;
  onCloseCliAgentRun?: (runId: string) => void;
  onRenameTitleChange: (title: string) => void;
  onSetActiveTab: (sessionId: string, tab: "agent") => void;
  onSubmitRename: (session: SessionSummary) => void;
};

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
  sessions,
  runtimeRunningSessionIds = [],
  sessionIdsNeedingApproval = [],
  statusLabel,
  t,
  workspaceActiveTab,
  onCancelRename,
  onContextMenu,
  onDragReference,
  onOpenDirectSession,
  onOpenCliAgentRun,
  onCloseCliAgentRun,
  onRenameTitleChange,
  onSetActiveTab,
  onSubmitRename,
}: AgentSessionTabStripProps) {
  if (cliAgentRuns.length === 0 && sessions.length === 0) {
    return null;
  }
  const approvalSessionIds = new Set(
    sessionIdsNeedingApproval.map((id) => String(id || "").trim()).filter(Boolean),
  );
  const runtimeSessionIds = new Set(
    runtimeRunningSessionIds.map((id) => String(id || "").trim()).filter(Boolean),
  );

  return (
    <div
      className={styles.agentSessionTabGroup}
      role="tablist"
      aria-label={lang === "zh" ? "Agent 会话" : "Agent sessions"}
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
        const statusIndicatorClass = agentSessionStatusIndicatorClassName(statusTone);
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
        const sessionStatusLabel = statusLabel(sessionStatus);
        const sessionStatusTitle = [statusShortLabel, sessionStatusLabel, sessionDisplay.modelLabel]
          .filter(Boolean)
          .join(" · ");
        const sessionHoverTitle = [sessionTitle, statusShortLabel, sessionSummary, sessionDisplay.modelLabel]
          .filter(Boolean)
          .join(" · ");
        const tabContextTarget = contextMenuSessionId === session.id;
        const tabEditing = editingSessionId === session.id;
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
              role="tab"
              aria-selected={tabActive}
              aria-current={tabActive ? "true" : undefined}
              onContextMenu={(event) => onContextMenu(event, session)}
              title={sessionHoverTitle}
            >
              <span className={styles.agentSessionTabIcon} aria-hidden="true">
                <Bot size={14} />
              </span>
              <span className={styles.agentSessionTabCopy}>
                <span className={styles.agentSessionTabKicker}>
                  {t("agentSession")}
                </span>
                <VNativeInput
                  className={styles.agentSessionTabTitleInput}
                  value={editingSessionTitle}
                  maxLength={120}
                  autoFocus
                  onChange={(event) => onRenameTitleChange(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      onSubmitRename(session);
                    }
                    if (event.key === "Escape") {
                      event.preventDefault();
                      onCancelRename();
                    }
                  }}
                  aria-label={t("renameSession")}
                />
              </span>
              <span className={styles.agentSessionTabEditActions}>
                <VIconButton
                  type="button"
                  className={styles.agentSessionTabEditButton}
                  onPress={() => onSubmitRename(session)}
                  isDisabled={sessionRenamePending}
                  title={t("saveSessionName")}
                  label={`${t("saveSessionName")} ${sessionTitle}`}
                  icon={<Check size={13} />}
                />
                <VIconButton
                  type="button"
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
            className={tabClassName}
            role="tab"
            aria-selected={tabActive}
            aria-current={tabActive ? "true" : undefined}
            {...dragReferenceProps}
            onContextMenu={(event) => onContextMenu(event, session)}
            title={sessionHoverTitle}
          >
            <VButton
              type="button"
              className={tabMainActionClassName}
              data-session-tab-active={tabActive ? "true" : "false"}
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
                {tabActive ? (
                  <span className={styles.agentSessionTabCurrentBadge}>
                    {lang === "zh" ? "当前" : "Now"}
                  </span>
                ) : null}
                <span
                  className={[
                    styles.agentSessionTabTitle,
                    tabActive ? styles.agentSessionTabTitleActive : "",
                  ].filter(Boolean).join(" ")}
                  title={sessionHoverTitle}
                >{sessionTitle}</span>
              </span>
              {statusTone !== "none" ? (
                <span
                  className={[
                    styles.agentSessionTabStatus,
                    tabActive ? "" : styles.agentSessionTabStatusMuted,
                  ].filter(Boolean).join(" ")}
                >
                  <span
                    className={statusIndicatorClass}
                    aria-hidden="true"
                    title={sessionStatusTitle}
                  >
                    {statusTone === "running" || statusTone === "approval" ? (
                      <LoaderCircle size={11} aria-hidden="true" className={styles.agentSessionTabStatusSpinner} />
                    ) : null}
                  </span>
                  {statusShortLabel ? (
                    <span
                      className={[
                        styles.agentSessionTabStatusText,
                        tabActive ? styles.agentSessionTabStatusTextActive : "",
                      ].filter(Boolean).join(" ")}
                      title={sessionStatusTitle}
                    >
                      {statusShortLabel}
                    </span>
                  ) : null}
                </span>
              ) : null}
            </VButton>
          </div>
        );
      })}
      {cliAgentRuns.map((run) => {
        const tabActive = activeCliAgentRunId === run.id;
        const statusTone = agentSessionStatusTone(run.status);
        const statusIndicatorClass = agentSessionStatusIndicatorClassName(statusTone);
        const statusShortLabel = agentSessionStatusShortLabel(statusTone, lang);
        const runStatusLabel = statusLabel(run.status);
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
        return (
          <div
            key={run.id}
            className={`${tabClassName} ${styles.agentSessionTabClosable}`}
            role="tab"
            aria-selected={tabActive}
            aria-current={tabActive ? "true" : undefined}
            title={title}
          >
            <VButton
              type="button"
              className={tabMainActionClassName}
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
                {tabActive ? (
                  <span className={styles.agentSessionTabCurrentBadge}>
                    {lang === "zh" ? "当前" : "Now"}
                  </span>
                ) : null}
                <span
                  className={[
                    styles.agentSessionTabTitle,
                    tabActive ? styles.agentSessionTabTitleActive : "",
                  ].filter(Boolean).join(" ")}
                  title={title}
                >{run.title}</span>
              </span>
              {statusTone !== "none" ? (
                <span
                  className={[
                    styles.agentSessionTabStatus,
                    tabActive ? "" : styles.agentSessionTabStatusMuted,
                  ].filter(Boolean).join(" ")}
                >
                  <span
                    className={statusIndicatorClass}
                    aria-hidden="true"
                    title={[statusShortLabel, runStatusLabel].filter(Boolean).join(" · ")}
                  >
                    {statusTone === "running" || statusTone === "approval" ? (
                      <LoaderCircle size={11} aria-hidden="true" className={styles.agentSessionTabStatusSpinner} />
                    ) : null}
                  </span>
                  {statusShortLabel ? (
                    <span
                      className={[
                        styles.agentSessionTabStatusText,
                        tabActive ? styles.agentSessionTabStatusTextActive : "",
                      ].filter(Boolean).join(" ")}
                      title={statusShortLabel}
                    >
                      {statusShortLabel}
                    </span>
                  ) : null}
                </span>
              ) : null}
            </VButton>
            <VIconButton
              type="button"
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
  );
}
