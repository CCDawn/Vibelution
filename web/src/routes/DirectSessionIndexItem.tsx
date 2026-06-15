import { Bot, Check, CircleDot, Clock3, Cpu, MessageCircle, X } from "lucide-react";
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

function hasAsciiLetter(value: string) {
  return /[A-Za-z]/.test(value);
}

function hasCjkText(value: string) {
  return /[\u3400-\u9fff]/.test(value);
}

export function sessionAgentMetaLabel(session: Pick<SessionSummary, "agentCode" | "agentId">) {
  void session;
  return "";
}

export function showSessionFunctionLabel(display: AgentDisplayInfo, lang: "zh" | "en" = "zh") {
  const label = String(display.functionLabel ?? "").trim();
  if (!label) {
    return false;
  }
  const normalized = label.toLowerCase();
  if (lang === "zh" && (hasAsciiLetter(label) || !hasCjkText(label))) {
    return false;
  }
  return !(display.tone === "chat" && (label === "会话入口" || normalized === "chat entry"));
}

export function sessionModelTooltip(modelLabel: string | undefined, lang: "zh" | "en") {
  const label = String(modelLabel ?? "").trim();
  if (!label) {
    return "";
  }
  if (lang === "zh") {
    return hasAsciiLetter(label) ? "模型已绑定" : `模型：${label}`;
  }
  return `Model: ${label}`;
}

export function showSessionSummaryInline(summary: string | undefined, lang: "zh" | "en", sessionIsChild: boolean) {
  const text = String(summary ?? "").trim();
  if (!text) {
    return false;
  }
  const fallbackSummaries = new Set([
    lang === "zh" ? "暂无摘要" : "No summary yet",
    lang === "zh" ? "子对话独立工作中" : "Independent child session",
  ]);
  if (fallbackSummaries.has(text)) {
    return false;
  }
  if (lang === "zh" && hasAsciiLetter(text)) {
    return false;
  }
  return sessionIsChild;
}

export function isChildSession(session: SessionSummary | undefined | null) {
  return String(session?.sessionKind ?? "").trim() === "child";
}

export function isAgentRootSession(session: SessionSummary | undefined | null) {
  return Boolean(String(session?.agentId ?? "").trim()) && !isChildSession(session);
}

export function sessionUnreadCount(session: Pick<SessionSummary, "agentInboxPendingCount"> | undefined | null) {
  const count = Number(session?.agentInboxPendingCount ?? 0);
  return Number.isFinite(count) && count > 0 ? Math.floor(count) : 0;
}

export function sessionUnreadBadgeTitle(count: number, lang: "zh" | "en") {
  if (count <= 0) {
    return "";
  }
  return lang === "zh" ? `未读信息：${count} 条` : `${count} unread message${count === 1 ? "" : "s"}`;
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
  const sessionFunctionVisible = showSessionFunctionLabel(sessionDisplay, lang);
  const sessionModelTitle = sessionModelTooltip(sessionDisplay.modelLabel, lang);
  const sessionSummaryVisible = showSessionSummaryInline(sessionSummary, lang, sessionIsChild);
  const unreadCount = sessionUnreadCount(session);
  const unreadTitle = sessionUnreadBadgeTitle(unreadCount, lang);
  const sessionItemClassName = active
    ? `${styles.sessionItem} ${styles.directSessionItem} ${sessionIsChild ? styles.childTopLevelSessionItem : ""} ${styles.sessionItemActive}`
    : `${styles.sessionItem} ${styles.directSessionItem} ${sessionIsChild ? styles.childTopLevelSessionItem : ""}`;
  const avatarClassName = `${styles.conversationAvatar} ${styles.conversationAvatarDirect}`;
  const renameLabel = t(sessionIsChild ? "renameTask" : isAgentRootSession(session) ? "renameAgent" : "renameSession");
  const saveLabel = t(sessionIsChild ? "saveTaskName" : isAgentRootSession(session) ? "saveAgentName" : "saveSessionName");
  const kindLabel = sessionIsChild ? (lang === "zh" ? "子对话" : "Child") : (lang === "zh" ? "会话" : "Chat");
  const statusText = statusLabel(sessionStatus);
  const statusTitle = lang === "zh" && hasAsciiLetter(statusText) ? "状态" : `${lang === "zh" ? "状态：" : ""}${statusText}`;

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
              {unreadCount > 0 ? (
                <span className={styles.sessionCurrentBadge} title={unreadTitle} aria-label={unreadTitle}>
                  {unreadCount}
                </span>
              ) : null}
              <span className={styles.sessionState} title={statusTitle} aria-label={statusTitle}>
                <CircleDot size={10} aria-hidden="true" />
              </span>
            </span>
            {sessionSummaryVisible ? (
              <span className={styles.sessionItemSummary} title={sessionSummary}>
                {sessionSummary}
              </span>
            ) : null}
            <span className={styles.conversationMetaRow}>
              <span className={`${styles.conversationKindBadge} ${sessionIsChild ? styles.conversationKindBadgeChild : styles.conversationKindBadgeDirect}`} title={kindLabel} aria-label={kindLabel}>
                <MessageCircle size={10} aria-hidden="true" />
              </span>
              {sessionAgentMeta ? <span>{sessionAgentMeta}</span> : null}
              {sessionFunctionVisible ? (
                <span className={`${styles.agentRoleTag} ${styles[agentRoleClass(sessionDisplay.tone)]}`} title={sessionDisplay.functionLabel}>
                  <Bot size={10} aria-hidden="true" />
                  {sessionDisplay.functionLabel}
                </span>
              ) : null}
              {sessionModelTitle ? (
                <span className={styles.agentModelTag} title={sessionModelTitle} aria-label={sessionModelTitle}>
                  <Cpu size={10} aria-hidden="true" />
                </span>
              ) : null}
              <Clock3 size={10} aria-hidden="true" />
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
              {unreadCount > 0 ? (
                <span className={styles.sessionCurrentBadge} title={unreadTitle} aria-label={unreadTitle}>
                  {unreadCount}
                </span>
              ) : null}
              <span className={styles.sessionState} title={statusTitle} aria-label={statusTitle}>
                <CircleDot size={10} aria-hidden="true" />
              </span>
            </span>
            {sessionSummaryVisible ? (
              <span className={styles.sessionItemSummary} title={sessionSummary}>
                {sessionSummary}
              </span>
            ) : null}
            <span className={styles.conversationMetaRow}>
              <span className={`${styles.conversationKindBadge} ${sessionIsChild ? styles.conversationKindBadgeChild : styles.conversationKindBadgeDirect}`} title={kindLabel} aria-label={kindLabel}>
                <MessageCircle size={10} aria-hidden="true" />
              </span>
              {sessionAgentMeta ? <span>{sessionAgentMeta}</span> : null}
              {sessionFunctionVisible ? (
                <span className={`${styles.agentRoleTag} ${styles[agentRoleClass(sessionDisplay.tone)]}`} title={sessionDisplay.functionLabel}>
                  <Bot size={10} aria-hidden="true" />
                  {sessionDisplay.functionLabel}
                </span>
              ) : null}
              {sessionModelTitle ? (
                <span className={styles.agentModelTag} title={sessionModelTitle} aria-label={sessionModelTitle}>
                  <Cpu size={10} aria-hidden="true" />
                </span>
              ) : null}
              <Clock3 size={10} aria-hidden="true" />
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
