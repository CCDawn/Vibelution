import { Bot, Check, Clock3, Cpu, LoaderCircle, MessageCircle, X } from "lucide-react";
import type { DragEvent, KeyboardEvent, MouseEvent } from "react";

import type { AgentInstance, SessionSummary } from "../api/types";
import { VButton, VIconButton } from "../components/vui";
import type { TranslationKey } from "../i18n/dictionary";
import {
  sessionAgentDisplayInfo,
  type AgentDisplayInfo,
  type ModelLabelResolver,
} from "./agentDisplay";
import styles from "./ChatCodingRoute.styles";

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
  if (lang === "zh" && (hasAsciiLetter(label) || !hasCjkText(label))) {
    return false;
  }
  return true;
}

export function sessionModelTooltip(modelLabel: string | undefined, lang: "zh" | "en") {
  const label = String(modelLabel ?? "").trim();
  if (!label) {
    return "";
  }
  if (lang === "zh") {
    return `模型：${label}`;
  }
  return `Model: ${label}`;
}

export function sessionModelBadgeLabel(modelLabel: string | undefined) {
  return String(modelLabel ?? "").trim();
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

export function isChildSession(session: Pick<SessionSummary, "sessionKind"> | undefined | null) {
  return String(session?.sessionKind ?? "").trim() === "child";
}

export function isAgentRootSession(session: Pick<SessionSummary, "agentId" | "sessionKind"> | undefined | null) {
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

export function sessionStatusValue(session: Pick<SessionSummary, "childStatus" | "currentPhase" | "status" | "sessionKind">) {
  const candidates = isChildSession(session)
    ? [session.childStatus, session.currentPhase, session.status]
    : [session.currentPhase, session.status];
  return candidates.find(sessionIsRunningStatus) || candidates.find((value) => String(value ?? "").trim()) || "";
}

export function sessionIsRunningStatus(value: string | null | undefined) {
  const status = String(value ?? "").trim().toLowerCase();
  return ["queued", "running", "thinking", "tooling", "answering", "planning", "reading", "editing", "verifying", "starting"].includes(status);
}

export function sessionRunningBadgeLabel(lang: "zh" | "en") {
  return lang === "zh" ? "运行中" : "Running";
}

export function sessionRunningBadgeTitle(statusText: string, lang: "zh" | "en") {
  const text = String(statusText || "").trim();
  if (!text) {
    return sessionRunningBadgeLabel(lang);
  }
  return lang === "zh" ? `正在运行：${text}` : `Running: ${text}`;
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
  const sessionStatus = sessionStatusValue(session);
  const sessionAgentMeta = sessionAgentMetaLabel(session);
  const sessionFunctionVisible = showSessionFunctionLabel(sessionDisplay, lang);
  const sessionModelLabel = sessionModelBadgeLabel(sessionDisplay.modelLabel);
  const sessionModelTitle = sessionModelTooltip(sessionDisplay.modelLabel, lang);
  const sessionSummaryVisible = showSessionSummaryInline(sessionSummary, lang, sessionIsChild);
  const unreadCount = sessionUnreadCount(session);
  const unreadTitle = sessionUnreadBadgeTitle(unreadCount, lang);
  const sessionRunning = sessionIsRunningStatus(sessionStatus);
  const sessionItemClassName = active
    ? `${styles.sessionItem} ${styles.directSessionItem} ${sessionIsChild ? styles.childTopLevelSessionItem : ""} ${styles.sessionItemActive}`
    : `${styles.sessionItem} ${styles.directSessionItem} ${sessionIsChild ? styles.childTopLevelSessionItem : ""}`;
  const avatarClassName = `${styles.conversationAvatar} ${styles.conversationAvatarDirect}`;
  const renameLabel = t(sessionIsChild ? "renameTask" : isAgentRootSession(session) ? "renameAgent" : "renameSession");
  const saveLabel = t(sessionIsChild ? "saveTaskName" : isAgentRootSession(session) ? "saveAgentName" : "saveSessionName");
  const kindLabel = sessionIsChild ? (lang === "zh" ? "子对话" : "Child") : (lang === "zh" ? "会话" : "Chat");
  const statusText = statusLabel(sessionStatus);
  const statusTitle = sessionRunningBadgeTitle(statusText, lang);
  const currentTitle = t("currentSession");
  const currentBadgeLabel = lang === "zh" ? "当前" : "Current";
  const runningBadgeLabel = sessionRunningBadgeLabel(lang);

  const statusCluster = (
    <span className={styles.sessionStatusCluster}>
      {active ? (
        <span
          className={styles.sessionCurrentBadge}
          title={currentTitle}
          aria-label={currentTitle}
        >
          {currentBadgeLabel}
        </span>
      ) : null}
      {sessionRunning ? (
        <span className={styles.sessionRunningBadge} title={statusTitle} aria-label={statusTitle}>
          <LoaderCircle size={10} aria-hidden="true" />
          <span>{runningBadgeLabel}</span>
        </span>
      ) : null}
      {unreadCount > 0 ? (
        <span className={styles.sessionUnreadBadge} title={unreadTitle} aria-label={unreadTitle}>
          {unreadCount}
        </span>
      ) : null}
    </span>
  );

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
  const dragSessionProps = {
    draggable: true,
    onDragStart,
  };

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
              <span className={styles.conversationTitleMain}>
                <input
                  className={styles.sessionTitleInput}
                  value={editingTitle}
                  maxLength={120}
                  autoFocus
                  onChange={(event) => onRenameTitleChange(event.target.value)}
                  onKeyDown={handleTitleKeyDown}
                  aria-label={renameLabel}
                />
                {sessionModelTitle ? (
                  <span className={`${styles.agentModelTag} ${styles.agentModelTitleTag}`} title={sessionModelTitle} aria-label={sessionModelTitle}>
                    <Cpu size={10} aria-hidden="true" />
                    <span>{sessionModelLabel}</span>
                  </span>
                ) : null}
              </span>
              {statusCluster}
            </span>
            {sessionSummaryVisible ? (
              <span className={styles.sessionItemSummary} title={sessionSummary}>
                {sessionSummary}
              </span>
            ) : null}
            <span className={styles.conversationMetaRow}>
              <span className={styles.conversationMetaMain}>
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
              </span>
              <span className={styles.conversationMetaTime}>
                <Clock3 size={10} aria-hidden="true" />
                <time>{formatTime(session.updatedAt || session.lastActive)}</time>
              </span>
            </span>
            {missingAgentMessage ? <span className={styles.agentMissingLine}>{missingAgentMessage}</span> : null}
          </span>
        </div>
      ) : (
        <VButton
          type="button"
          className={styles.sessionItemMain}
          {...dragSessionProps}
          onPress={() => onOpen(session.id)}
          aria-current={active ? "true" : undefined}
        >
          {renderSessionAvatar(avatarClassName, sessionAvatarImageUrl, sessionAvatarFallback)}
          <span className={styles.conversationCopy}>
            <span className={styles.conversationTitleRow}>
              <span className={styles.conversationTitleMain}>
                <span className={styles.sessionItemTitle}>{sessionTitle}</span>
                {sessionModelTitle ? (
                  <span className={`${styles.agentModelTag} ${styles.agentModelTitleTag}`} title={sessionModelTitle} aria-label={sessionModelTitle}>
                    <Cpu size={10} aria-hidden="true" />
                    <span>{sessionModelLabel}</span>
                  </span>
                ) : null}
              </span>
              {statusCluster}
            </span>
            {sessionSummaryVisible ? (
              <span className={styles.sessionItemSummary} title={sessionSummary}>
                {sessionSummary}
              </span>
            ) : null}
            <span className={styles.conversationMetaRow}>
              <span className={styles.conversationMetaMain}>
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
              </span>
              <span className={styles.conversationMetaTime}>
                <Clock3 size={10} aria-hidden="true" />
                <time>{formatTime(session.updatedAt || session.lastActive)}</time>
              </span>
            </span>
            {missingAgentMessage ? <span className={styles.agentMissingLine}>{missingAgentMessage}</span> : null}
          </span>
        </VButton>
      )}
      {editing ? (
        <div className={styles.sessionActionStack}>
          <VIconButton
            type="button"
            className={styles.sessionIconButton}
            onPress={() => onSubmitRename(session)}
            isDisabled={renamePending}
            title={saveLabel}
            label={`${saveLabel} ${sessionTitle}`}
            icon={<Check size={15} />}
          />
          <VIconButton
            type="button"
            className={styles.sessionIconButton}
            onPress={onCancelRename}
            isDisabled={renamePending}
            title={t("cancelRenameSession")}
            label={t("cancelRenameSession")}
            icon={<X size={15} />}
          />
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
