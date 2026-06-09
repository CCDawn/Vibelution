import { Check, X } from "lucide-react";
import type { DragEvent, KeyboardEvent, MouseEvent } from "react";

import type { AgentInstance, SessionSummary } from "../api/types";
import type { TranslationKey } from "../i18n/dictionary";
import {
  sessionAgentDisplayInfo,
  type AgentDisplayInfo,
  type ModelLabelResolver,
} from "./agentDisplay";
import styles from "./ChatCodingRoute.module.css";

export function sessionListTitle(
  session: Pick<SessionSummary, "id" | "title" | "agentDisplayName" | "taskTitle" | "resultCard" | "sessionKind">,
) {
  const sessionKind = String(session.sessionKind ?? "").trim();
  if (sessionKind === "child") {
    return String(
      session.taskTitle
      || session.resultCard?.title
      || session.title
      || session.id
      || "",
    ).trim();
  }
  return String(
    session.title
    || session.agentDisplayName
    || session.id
    || "",
  ).trim();
}

function compactAgentIdentifier(value: unknown) {
  const raw = String(value ?? "").trim();
  if (!raw) {
    return "";
  }
  const withoutPrefix = raw.replace(/^agent[-_]/i, "");
  if (withoutPrefix.length <= 18) {
    return withoutPrefix;
  }
  return withoutPrefix.slice(-12);
}

export function sessionAgentMetaLabel(session: Pick<SessionSummary, "agentCode" | "agentId">) {
  const code = String(session.agentCode ?? "").trim();
  if (code) {
    return `Agent ${code}`;
  }
  const compactId = compactAgentIdentifier(session.agentId);
  return compactId ? `Agent ${compactId}` : "";
}

export function showSessionFunctionLabel(display: AgentDisplayInfo) {
  const label = String(display.functionLabel ?? "").trim();
  if (!label) {
    return false;
  }
  const normalized = label.toLowerCase();
  return !(display.tone === "chat" && (label === "会话入口" || normalized === "chat entry"));
}

export function isChildSession(session: SessionSummary | undefined | null) {
  return String(session?.sessionKind ?? "").trim() === "child";
}

export function isAgentRootSession(session: SessionSummary | undefined | null) {
  return Boolean(String(session?.agentId ?? "").trim()) && !isChildSession(session);
}

export type DirectSessionIndexViewModel = {
  itemIsNotice: boolean;
  itemMessage: string;
  missingAgentMessage: string;
  sessionAgentMeta: string;
  sessionDisplay: AgentDisplayInfo;
  sessionSummary: string;
  sessionTitle: string;
};

type DirectSessionIndexViewModelOptions = {
  addToReviewSucceededLabel: string;
  agent: AgentInstance | undefined;
  deleteBusyLabel: string;
  itemError: string;
  lang: "zh" | "en";
  resolveModelLabel?: ModelLabelResolver;
  session: SessionSummary;
  sessionBusy: boolean;
};

export function buildDirectSessionIndexViewModel({
  addToReviewSucceededLabel,
  agent,
  deleteBusyLabel,
  itemError,
  lang,
  resolveModelLabel,
  session,
  sessionBusy,
}: DirectSessionIndexViewModelOptions): DirectSessionIndexViewModel {
  const deleteBusyReason = sessionBusy ? deleteBusyLabel : "";
  const itemMessage = itemError || deleteBusyReason;
  const itemIsNotice = itemError
    ? itemError.startsWith(addToReviewSucceededLabel)
    : Boolean(deleteBusyReason);
  const sessionDisplay = sessionAgentDisplayInfo(session, agent, lang, resolveModelLabel);
  const sessionAgentMeta = sessionAgentMetaLabel(session);
  const missingAgentMessage = session.agentMissing
    ? session.agentStatusMessage || (lang === "zh" ? "缺少有效 Agent，当前会话缺少可运行内容。" : "Missing valid Agent. This session has no runnable Agent content.")
    : "";
  const sessionIsChild = isChildSession(session);
  const sessionTitle = sessionListTitle(session) || sessionDisplay.name;
  const sessionSummary =
    (sessionIsChild ? (session.resultCard?.summary || session.taskSummary) : session.taskSummary)
    || (sessionIsChild
      ? (lang === "zh" ? "子对话独立工作中" : "Independent child session")
      : (lang === "zh" ? "暂无摘要" : "No summary yet"));

  return {
    itemIsNotice,
    itemMessage,
    missingAgentMessage,
    sessionAgentMeta,
    sessionDisplay,
    sessionSummary,
    sessionTitle,
  };
}

function agentRoleClass(tone: string) {
  return `agentRoleTag_${tone}`;
}

type DirectSessionIndexItemProps = {
  active: boolean;
  editing: boolean;
  editingTitle: string;
  itemMessage: string;
  itemIsNotice: boolean;
  missingAgentMessage: string;
  renamePending: boolean;
  session: SessionSummary;
  sessionAvatarFallback: string;
  sessionAvatarImageUrl: string;
  sessionDisplay: AgentDisplayInfo;
  sessionSummary: string;
  sessionTitle: string;
  lang: "zh" | "en";
  statusLabel: (status: string) => string;
  formatTime: (value: string) => string;
  t: (key: TranslationKey) => string;
  onCancelRename: () => void;
  onContextMenu: (event: MouseEvent<HTMLDivElement>, session: SessionSummary) => void;
  onDragStart: (event: DragEvent<HTMLElement>) => void;
  onOpen: (sessionId: string) => void;
  onRenameTitleChange: (title: string) => void;
  onSubmitRename: (session: SessionSummary) => void;
};

function renderSessionAvatar(className: string, imageUrl: string | undefined, fallback: string) {
  return (
    <span className={className} aria-hidden="true">
      {imageUrl ? <img src={imageUrl} alt="" className={styles.agentAvatarImage} /> : fallback}
    </span>
  );
}

export function DirectSessionIndexItem({
  active,
  editing,
  editingTitle,
  itemMessage,
  itemIsNotice,
  missingAgentMessage,
  renamePending,
  session,
  sessionAvatarFallback,
  sessionAvatarImageUrl,
  sessionDisplay,
  sessionSummary,
  sessionTitle,
  lang,
  statusLabel,
  formatTime,
  t,
  onCancelRename,
  onContextMenu,
  onDragStart,
  onOpen,
  onRenameTitleChange,
  onSubmitRename,
}: DirectSessionIndexItemProps) {
  const sessionIsChild = isChildSession(session);
  const sessionStatus = sessionIsChild ? (session.childStatus || session.currentPhase || session.status) : session.status;
  const sessionAgentMeta = sessionAgentMetaLabel(session);
  const sessionFunctionVisible = showSessionFunctionLabel(sessionDisplay);
  const sessionItemClassName = active
    ? `${styles.sessionItem} ${styles.directSessionItem} ${sessionIsChild ? styles.childTopLevelSessionItem : ""} ${styles.sessionItemActive}`
    : `${styles.sessionItem} ${styles.directSessionItem} ${sessionIsChild ? styles.childTopLevelSessionItem : ""}`;
  const avatarClassName = `${styles.conversationAvatar} ${styles.conversationAvatarDirect}`;
  const renameLabel = t(sessionIsChild ? "renameTask" : isAgentRootSession(session) ? "renameAgent" : "renameSession");
  const saveLabel = t(sessionIsChild ? "saveTaskName" : isAgentRootSession(session) ? "saveAgentName" : "saveSessionName");
  const kindLabel = sessionIsChild ? (lang === "zh" ? "子对话" : "Child") : (lang === "zh" ? "会话" : "Chat");

  function handleTitleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter") {
      event.preventDefault();
      onSubmitRename(session);
    }
    if (event.key === "Escape") {
      event.preventDefault();
      onCancelRename();
    }
  }

  return (
    <div
      aria-current={active ? "true" : undefined}
      onContextMenu={(event) => onContextMenu(event, session)}
      className={sessionItemClassName}
    >
      {editing ? (
        <div className={styles.sessionItemMain}>
          {renderSessionAvatar(avatarClassName, sessionAvatarImageUrl, sessionAvatarFallback)}
          <span className={styles.conversationCopy}>
            <span className={styles.conversationTitleRow}>
              <input
                className={styles.sessionTitleInput}
                value={editingTitle}
                maxLength={120}
                autoFocus
                onChange={(event) => onRenameTitleChange(event.target.value)}
                onKeyDown={handleTitleKeyDown}
                aria-label={renameLabel}
              />
              {active ? <span className={styles.sessionCurrentBadge}>{t("currentSession")}</span> : null}
              <span className={styles.sessionState}>{statusLabel(sessionStatus)}</span>
            </span>
            <span className={styles.sessionItemSummary} title={sessionSummary}>
              {sessionSummary}
            </span>
            <span className={styles.conversationMetaRow}>
              <span className={`${styles.conversationKindBadge} ${sessionIsChild ? styles.conversationKindBadgeChild : styles.conversationKindBadgeDirect}`}>
                {kindLabel}
              </span>
              {sessionAgentMeta ? <span>{sessionAgentMeta}</span> : null}
              {sessionFunctionVisible ? (
                <span className={`${styles.agentRoleTag} ${styles[agentRoleClass(sessionDisplay.tone)]}`}>
                  {sessionDisplay.functionLabel}
                </span>
              ) : null}
              {sessionDisplay.modelLabel ? (
                <span className={styles.agentModelTag} title={sessionDisplay.modelLabel}>
                  {sessionDisplay.modelLabel}
                </span>
              ) : null}
              <time>{formatTime(session.updatedAt || session.lastActive)}</time>
            </span>
            {missingAgentMessage ? <span className={styles.agentMissingLine}>{missingAgentMessage}</span> : null}
          </span>
        </div>
      ) : (
        <button
          type="button"
          className={styles.sessionItemMain}
          draggable
          onDragStart={onDragStart}
          onClick={() => onOpen(session.id)}
          aria-current={active ? "true" : undefined}
        >
          {renderSessionAvatar(avatarClassName, sessionAvatarImageUrl, sessionAvatarFallback)}
          <span className={styles.conversationCopy}>
            <span className={styles.conversationTitleRow}>
              <span className={styles.sessionItemTitle}>{sessionTitle}</span>
              {active ? <span className={styles.sessionCurrentBadge}>{t("currentSession")}</span> : null}
              <span className={styles.sessionState}>{statusLabel(sessionStatus)}</span>
            </span>
            <span className={styles.sessionItemSummary} title={sessionSummary}>
              {sessionSummary}
            </span>
            <span className={styles.conversationMetaRow}>
              <span className={`${styles.conversationKindBadge} ${sessionIsChild ? styles.conversationKindBadgeChild : styles.conversationKindBadgeDirect}`}>
                {kindLabel}
              </span>
              {sessionAgentMeta ? <span>{sessionAgentMeta}</span> : null}
              {sessionFunctionVisible ? (
                <span className={`${styles.agentRoleTag} ${styles[agentRoleClass(sessionDisplay.tone)]}`}>
                  {sessionDisplay.functionLabel}
                </span>
              ) : null}
              {sessionDisplay.modelLabel ? (
                <span className={styles.agentModelTag} title={sessionDisplay.modelLabel}>
                  {sessionDisplay.modelLabel}
                </span>
              ) : null}
              <time>{formatTime(session.updatedAt || session.lastActive)}</time>
            </span>
            {missingAgentMessage ? <span className={styles.agentMissingLine}>{missingAgentMessage}</span> : null}
          </span>
        </button>
      )}
      {editing ? (
        <div className={styles.sessionActionStack}>
          <button
            type="button"
            className={styles.sessionIconButton}
            onClick={() => onSubmitRename(session)}
            disabled={renamePending}
            title={saveLabel}
            aria-label={`${saveLabel} ${sessionTitle}`}
          >
            <Check size={15} />
          </button>
          <button
            type="button"
            className={styles.sessionIconButton}
            onClick={onCancelRename}
            disabled={renamePending}
            title={t("cancelRenameSession")}
            aria-label={t("cancelRenameSession")}
          >
            <X size={15} />
          </button>
        </div>
      ) : null}
      {itemMessage ? (
        <p className={itemIsNotice ? styles.sessionItemNotice : styles.sessionItemError}>
          {itemMessage}
        </p>
      ) : null}
    </div>
  );
}
