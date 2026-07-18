import { Bot, Check, MessageCircleHeart, SquareTerminal, X } from "lucide-react";
import type { DragEvent, MouseEvent as ReactMouseEvent } from "react";

import type { AgentInstance, SessionReferenceAttachment, SessionSummary } from "../api/types";
import { VButton, VIconButton, VNativeInput } from "../components/vui";
import type { TranslationKey } from "../i18n/dictionary";
import { sessionAgentDisplayInfo } from "./agentDisplay";
import { isChildSession } from "./DirectSessionIndexItem";
import styles from "./AgentSessionTabStrip.styles";

export type CliAgentRunTab = {
  id: string;
  title: string;
  summary: string;
  status: string;
  agentType: string;
  mode: string;
};

type AgentSessionStatusTone = "running" | "error" | "done";

function agentSessionStatusTone(status: string): AgentSessionStatusTone {
  const value = status.trim().toLowerCase();
  if (
    [
      "running",
      "active",
      "thinking",
      "tooling",
      "tool",
      "answering",
      "streaming",
      "pending",
      "checking",
      "planning",
      "reading",
      "working",
      "in_progress",
    ].includes(value)
  ) {
    return "running";
  }
  if (["error", "failed", "failure", "blocked", "danger", "crashed", "unhealthy"].includes(value)) {
    return "error";
  }
  return "done";
}

function agentSessionStatusDotClassName(status: string) {
  const tone = agentSessionStatusTone(status);
  return [
    styles.agentSessionTabStatusDot,
    tone === "running" ? styles.agentSessionTabStatusDotRunning : "",
    tone === "error" ? styles.agentSessionTabStatusDotError : "",
    tone === "done" ? styles.agentSessionTabStatusDotDone : "",
  ].filter(Boolean).join(" ");
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

  return (
    <div
      className={styles.agentSessionTabGroup}
      role="tablist"
      aria-label={lang === "zh" ? "Agent 会话" : "Agent sessions"}
    >
      {sessions.map((session) => {
        const sessionIsChild = isChildSession(session);
        const sessionAgent = session.agentId ? agentsById.get(session.agentId) : undefined;
        const sessionDisplay = sessionAgentDisplayInfo(session, sessionAgent, lang, resolveModelLabel);
        const sessionStatus = sessionIsChild ? (session.childStatus || session.currentPhase || session.status) : session.status;
        const sessionTitle =
          (sessionIsChild ? (session.taskTitle || session.resultCard?.title || session.title) : session.title)
          || sessionDisplay.name
          || t("agentSession");
        const sessionSummary =
          (sessionIsChild ? (session.resultCard?.summary || session.taskSummary) : session.taskSummary)
          || sessionDisplay.modelLabel
          || "";
        const sessionStatusLabel = statusLabel(sessionStatus);
        const sessionStatusTitle = [sessionStatusLabel, sessionDisplay.modelLabel].filter(Boolean).join(" · ");
        const sessionHoverTitle = [sessionTitle, sessionStatusLabel, sessionSummary, sessionDisplay.modelLabel]
          .filter(Boolean)
          .join(" · ");
        const tabActive = activeSessionId === session.id && workspaceActiveTab === "agent" && !activeCliAgentRunId;
        const tabContextTarget = contextMenuSessionId === session.id;
        const tabEditing = editingSessionId === session.id;
        const tabClassName = [
          styles.agentSessionTab,
          sessionIsChild ? styles.agentSessionTabChild : styles.agentSessionTabRoot,
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
                {sessionIsChild ? <MessageCircleHeart size={14} /> : <Bot size={14} />}
              </span>
              <span className={styles.agentSessionTabCopy}>
                <span className={styles.agentSessionTabKicker}>
                  {sessionIsChild ? (lang === "zh" ? "子对话" : "Child") : t("agentSession")}
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
                  aria-label={t(sessionIsChild ? "renameTask" : "renameAgent")}
                />
              </span>
              <span className={styles.agentSessionTabEditActions}>
                <VIconButton
                  type="button"
                  className={styles.agentSessionTabEditButton}
                  onPress={() => onSubmitRename(session)}
                  isDisabled={sessionRenamePending}
                  title={t(sessionIsChild ? "saveTaskName" : "saveAgentName")}
                  label={`${t(sessionIsChild ? "saveTaskName" : "saveAgentName")} ${sessionTitle}`}
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
              onPress={() => {
                if (activeSessionId === session.id) {
                  onSetActiveTab(session.id, "agent");
                  return;
                }
                onOpenDirectSession(session.id);
              }}
              title={sessionHoverTitle}
            >
              <span className={styles.agentSessionTabIcon} aria-hidden="true">
                {sessionIsChild ? <MessageCircleHeart size={14} /> : <Bot size={14} />}
              </span>
              <span
                className={styles.agentSessionTabTitle}
                title={sessionHoverTitle}
              >{sessionTitle}</span>
              <span
                className={agentSessionStatusDotClassName(sessionStatus)}
                role="img"
                aria-label={sessionStatusLabel}
                title={sessionStatusTitle}
              />
            </VButton>
          </div>
        );
      })}
      {cliAgentRuns.map((run) => {
        const tabActive = activeCliAgentRunId === run.id;
        const runStatusLabel = statusLabel(run.status);
        const title = [run.title, runStatusLabel, run.summary].filter(Boolean).join(" · ");
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
              onPress={() => onOpenCliAgentRun?.(run.id)}
              title={title}
            >
              <span className={styles.agentSessionTabIcon} aria-hidden="true">
                <SquareTerminal size={14} />
              </span>
              <span className={styles.agentSessionTabTitle} title={title}>{run.title}</span>
              <span
                className={agentSessionStatusDotClassName(run.status)}
                role="img"
                aria-label={runStatusLabel}
                title={runStatusLabel}
              />
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
