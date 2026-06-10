import { Bot, Check, MessageCircleHeart, X } from "lucide-react";
import type { DragEvent, MouseEvent as ReactMouseEvent } from "react";

import type { AgentInstance, SessionReferenceAttachment, SessionSummary } from "../api/types";
import type { TranslationKey } from "../i18n/dictionary";
import { sessionAgentDisplayInfo } from "./agentDisplay";
import { isChildSession } from "./DirectSessionIndexItem";
import styles from "./ChatCodingRoute.module.css";

export type AgentSessionTabStripProps = {
  activeSessionId: string | null;
  agentsById: Map<string, AgentInstance>;
  buildSessionReferencePayload: (
    session: SessionSummary,
    displayName: string,
    summary: string,
  ) => SessionReferenceAttachment;
  editingSessionId: string | null;
  editingSessionTitle: string;
  lang: "zh" | "en";
  renamePending: boolean;
  renameSessionId: string;
  resolveModelLabel: (modelId: string) => string | undefined;
  sessions: SessionSummary[];
  statusLabel: (status: string) => string;
  t: (key: TranslationKey) => string;
  workspaceActiveTab: string;
  onCancelRename: () => void;
  onContextMenu: (event: ReactMouseEvent<HTMLElement>, session: SessionSummary) => void;
  onDragReference: (event: DragEvent<HTMLElement>, reference: SessionReferenceAttachment) => void;
  onOpenDirectSession: (sessionId: string) => void;
  onRenameTitleChange: (title: string) => void;
  onSetActiveTab: (sessionId: string, tab: "agent") => void;
  onSubmitRename: (session: SessionSummary) => void;
};

export function AgentSessionTabStrip({
  activeSessionId,
  agentsById,
  buildSessionReferencePayload,
  editingSessionId,
  editingSessionTitle,
  lang,
  renamePending,
  renameSessionId,
  resolveModelLabel,
  sessions,
  statusLabel,
  t,
  workspaceActiveTab,
  onCancelRename,
  onContextMenu,
  onDragReference,
  onOpenDirectSession,
  onRenameTitleChange,
  onSetActiveTab,
  onSubmitRename,
}: AgentSessionTabStripProps) {
  if (sessions.length <= 1) {
    return null;
  }

  return (
    <div className={styles.agentSessionTabGroup} aria-label={lang === "zh" ? "Agent 会话" : "Agent sessions"}>
      {sessions.map((session) => {
        const sessionIsChild = isChildSession(session);
        const sessionAgent = session.agentId ? agentsById.get(session.agentId) : undefined;
        const sessionDisplay = sessionAgentDisplayInfo(session, sessionAgent, lang, resolveModelLabel);
        const sessionStatus = sessionIsChild ? (session.childStatus || session.currentPhase || session.status) : session.status;
        const sessionTitle =
          (sessionIsChild ? (session.taskTitle || session.resultCard?.title || session.title) : sessionDisplay.name)
          || sessionDisplay.name
          || t("agentSession");
        const sessionSummary =
          (sessionIsChild ? (session.resultCard?.summary || session.taskSummary) : session.taskSummary)
          || sessionDisplay.modelLabel
          || "";
        const tabActive = activeSessionId === session.id && workspaceActiveTab === "agent";
        const tabEditing = editingSessionId === session.id;
        const tabClassName = [
          styles.agentSessionTab,
          sessionIsChild ? styles.agentSessionTabChild : styles.agentSessionTabRoot,
          tabActive ? styles.agentSessionTabActive : "",
          tabEditing ? styles.agentSessionTabEditing : "",
        ].filter(Boolean).join(" ");
        if (tabEditing) {
          const sessionRenamePending = renamePending && renameSessionId === session.id;
          return (
            <div
              key={session.id}
              className={tabClassName}
              aria-current={tabActive ? "true" : undefined}
              onContextMenu={(event) => onContextMenu(event, session)}
              title={[sessionTitle, sessionSummary].filter(Boolean).join(" · ")}
            >
              <span className={styles.agentSessionTabIcon} aria-hidden="true">
                {sessionIsChild ? <MessageCircleHeart size={14} /> : <Bot size={14} />}
              </span>
              <span className={styles.agentSessionTabCopy}>
                <span className={styles.agentSessionTabKicker}>
                  {sessionIsChild ? (lang === "zh" ? "子对话" : "Child") : t("agentSession")}
                </span>
                <input
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
                <button
                  type="button"
                  className={styles.agentSessionTabEditButton}
                  onClick={() => onSubmitRename(session)}
                  disabled={sessionRenamePending}
                  title={t(sessionIsChild ? "saveTaskName" : "saveAgentName")}
                  aria-label={`${t(sessionIsChild ? "saveTaskName" : "saveAgentName")} ${sessionTitle}`}
                >
                  <Check size={13} />
                </button>
                <button
                  type="button"
                  className={styles.agentSessionTabEditButton}
                  onClick={onCancelRename}
                  disabled={sessionRenamePending}
                  title={t("cancelRenameSession")}
                  aria-label={t("cancelRenameSession")}
                >
                  <X size={13} />
                </button>
              </span>
            </div>
          );
        }
        return (
          <button
            key={session.id}
            type="button"
            className={tabClassName}
            aria-current={tabActive ? "true" : undefined}
            draggable
            onDragStart={(event) =>
              onDragReference(
                event,
                buildSessionReferencePayload(session, sessionDisplay.name, sessionSummary),
              )}
            onContextMenu={(event) => onContextMenu(event, session)}
            onClick={() => {
              if (activeSessionId === session.id) {
                onSetActiveTab(session.id, "agent");
                return;
              }
              onOpenDirectSession(session.id);
            }}
            title={[sessionTitle, sessionSummary].filter(Boolean).join(" · ")}
          >
            <span className={styles.agentSessionTabIcon} aria-hidden="true">
              {sessionIsChild ? <MessageCircleHeart size={14} /> : <Bot size={14} />}
            </span>
            <span className={styles.agentSessionTabCopy}>
              <span className={styles.agentSessionTabKicker}>
                {sessionIsChild ? (lang === "zh" ? "子对话" : "Child") : t("agentSession")}
              </span>
              <span className={styles.agentSessionTabTitle}>{sessionTitle}</span>
            </span>
            <span className={styles.agentSessionTabMeta}>
              {statusLabel(sessionStatus)}
              {sessionDisplay.modelLabel ? ` · ${sessionDisplay.modelLabel}` : ""}
            </span>
          </button>
        );
      })}
    </div>
  );
}
