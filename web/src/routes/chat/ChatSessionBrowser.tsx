import { useMemo, useState } from "react";
import { Clock3, MessageSquareText, Plus, Search, SearchX, UsersRound } from "lucide-react";

import type { AgentInstance, SessionSummary } from "../../api/types";
import { VButton, VInput, VStateSurface } from "../../components/vui";
import { sessionAgentDisplayInfo } from "../agentDisplay";
import { groupSessionsByTimeline, type SessionListDateBucket } from "./sessionListGrouping";
import { formatRelativeTime } from "../chatShellFormat";
import { avatarImageUrlFrom, avatarInitials, renderAgentAvatar } from "./chatRoutePresentation";
import {
  resolveSessionActivityTone,
  sessionActivityLabel,
  sessionIsCompletedStatus,
  sessionIsErrorStatus,
  sessionIsRunningStatus,
  sessionStatusCandidates,
  type SessionActivityTone,
} from "../sessionActivityIndicator";
import styles from "./ChatSessionBrowser.styles";

export type ChatSessionBrowserProps = {
  sessions: SessionSummary[];
  agentsById: Map<string, AgentInstance>;
  activeSessionId: string | null;
  lang: "zh" | "en";
  resolveModelLabel: (modelId: string) => string | undefined;
  runtimeRunningSessionIds?: readonly string[];
  sessionIdsNeedingApproval?: readonly string[];
  loading?: boolean;
  error?: string;
  createPending?: boolean;
  createDisabled?: boolean;
  onOpen: (sessionId: string) => void;
  onCreate: () => void;
  onRetry: () => void;
};

type SessionStatusFilter = "all" | "running" | "attention" | "completed" | "ready";
type DisplayBucket = SessionListDateBucket | "undated";

const COPY = {
  zh: {
    eyebrow: "工作区",
    title: "全部会话",
    description: "按最近活动浏览 Agent、团队与项目对话。",
    create: "新建会话",
    search: "搜索会话、Agent 或团队",
    filterLabel: "按状态筛选会话",
    filters: { all: "全部", running: "进行中", attention: "待处理", completed: "已完成", ready: "可继续" },
    resultCount: (count: number) => `${count} 个会话`,
    groups: { today: "今天", yesterday: "昨天", thisWeek: "本周", earlier: "更早", undated: "日期未知" },
    unknownAgent: "未知 Agent",
    unknownModel: "模型未指定",
    noActivity: "暂无活动摘要",
    ready: "可继续",
    emptyTitle: "还没有会话",
    emptyDescription: "新建一个会话，开始与 Agent 协作。",
    noMatchesTitle: "没有找到匹配的会话",
    noMatchesDescription: "试试其他关键词，或清除筛选条件。",
    clearFilters: "清除筛选",
    loading: "正在加载会话…",
    loadingDescription: "正在整理最近的对话。",
    errorTitle: "会话暂时无法加载",
    retry: "重试",
    refreshing: "正在更新会话列表…",
    team: "团队",
  },
  en: {
    eyebrow: "WORKSPACE",
    title: "All sessions",
    description: "Browse Agent, team, and project conversations by recent activity.",
    create: "New session",
    search: "Search sessions, Agents, or teams",
    filterLabel: "Filter sessions by status",
    filters: { all: "All", running: "In progress", attention: "Needs attention", completed: "Completed", ready: "Ready" },
    resultCount: (count: number) => `${count} sessions`,
    groups: { today: "Today", yesterday: "Yesterday", thisWeek: "This week", earlier: "Earlier", undated: "Date unknown" },
    unknownAgent: "Unknown Agent",
    unknownModel: "Model not set",
    noActivity: "No activity summary",
    ready: "Ready",
    emptyTitle: "No sessions yet",
    emptyDescription: "Create a session to start working with an Agent.",
    noMatchesTitle: "No matching sessions",
    noMatchesDescription: "Try another query or clear the filters.",
    clearFilters: "Clear filters",
    loading: "Loading sessions…",
    loadingDescription: "Gathering recent conversations.",
    errorTitle: "Sessions could not be loaded",
    retry: "Retry",
    refreshing: "Updating sessions…",
    team: "Team",
  },
} as const;

function timestampFor(session: SessionSummary) {
  return String(session.updatedAt || session.lastActive || "").trim();
}

function teamNameFor(session: SessionSummary) {
  return String(
    session.teamName
      || session.experimentBinding?.experimentName
      || session.teamId
      || session.experimentBinding?.teamId
      || "",
  ).trim();
}

function toneMatches(tone: SessionActivityTone, filter: SessionStatusFilter, isCompleted: boolean) {
  if (filter === "all") return true;
  if (filter === "running") return tone === "running";
  if (filter === "attention") return tone === "approval" || tone === "error";
  if (filter === "completed") return isCompleted;
  return tone === "none";
}

function hasCompletedLifecycle(session: SessionSummary) {
  const candidates = sessionStatusCandidates(session);
  return !candidates.some(sessionIsErrorStatus)
    && !candidates.some(sessionIsRunningStatus)
    && candidates.some(sessionIsCompletedStatus);
}

function activityLabel(tone: SessionActivityTone, lang: "zh" | "en") {
  return sessionActivityLabel(tone, lang) || (lang === "zh" ? "可继续" : "Ready");
}

export function ChatSessionBrowser({
  sessions,
  agentsById,
  activeSessionId,
  lang,
  resolveModelLabel,
  runtimeRunningSessionIds = [],
  sessionIdsNeedingApproval = [],
  loading = false,
  error,
  createPending = false,
  createDisabled = false,
  onOpen,
  onCreate,
  onRetry,
}: ChatSessionBrowserProps) {
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<SessionStatusFilter>("all");
  const copy = COPY[lang];
  const locale = lang === "zh" ? "zh-CN" : "en-US";
  const nowMs = Date.now();
  const runtimeIds = useMemo(() => new Set(runtimeRunningSessionIds), [runtimeRunningSessionIds]);
  const approvalIds = useMemo(() => new Set(sessionIdsNeedingApproval), [sessionIdsNeedingApproval]);

  const rows = useMemo(() => sessions.map((session) => {
    const agent = session.agentId ? agentsById.get(session.agentId) : undefined;
    const display = sessionAgentDisplayInfo(session, agent, lang, resolveModelLabel);
    const tone = resolveSessionActivityTone(session, {
      needsApproval: approvalIds.has(session.id),
      isRuntimeRunning: runtimeIds.has(session.id),
      isActive: session.id === activeSessionId,
    });
    const timestamp = timestampFor(session);
    const summary = String(session.taskSummary || session.resultCard?.summary || "").trim();
    const teamName = teamNameFor(session);
    const avatarUrl = avatarImageUrlFrom(agent, session) || undefined;
    const fallback = avatarInitials(session.agentCode || agent?.agentCode, display.name, "AI");
    const isCompleted = hasCompletedLifecycle(session);
    return { session, display, tone, isCompleted, timestamp, summary, teamName, avatarUrl, fallback };
  }), [sessions, agentsById, lang, resolveModelLabel, approvalIds, runtimeIds, activeSessionId]);

  const normalizedQuery = query.trim().toLocaleLowerCase(locale);
  const filters: Array<{ id: SessionStatusFilter; label: string }> = [
    { id: "all", label: copy.filters.all },
    { id: "running", label: copy.filters.running },
    { id: "attention", label: copy.filters.attention },
    { id: "completed", label: copy.filters.completed },
    { id: "ready", label: copy.filters.ready },
  ];
  const filteredRows = rows.filter(({ session, display, tone, isCompleted, summary, teamName }) => {
    const searchable = [
      session.title,
      session.taskSummary,
      session.resultCard?.title,
      session.resultCard?.summary,
      display.name,
      display.functionLabel,
      display.modelLabel,
      teamName,
      session.teamId,
      ...(session.searchSnippets ?? []),
    ].filter(Boolean).join(" ").toLocaleLowerCase(locale);
    return searchable.includes(normalizedQuery) && toneMatches(tone, statusFilter, isCompleted);
  });
  const filteredSessions = filteredRows.map(({ session }) => session);
  const groupedSessions = useMemo(() => {
    const groups = groupSessionsByTimeline(filteredSessions, nowMs).map((group) => ({
      bucket: group.bucket as DisplayBucket,
      sessions: group.sessions,
    }));
    const datedIds = new Set(groups.flatMap((group) => group.sessions.map((session) => session.id)));
    const undated = filteredSessions
      .filter((session) => !datedIds.has(session.id))
      .sort((left, right) => String(left.title || left.id).localeCompare(String(right.title || right.id)));
    if (undated.length) groups.push({ bucket: "undated", sessions: undated });
    return groups;
  }, [filteredSessions, nowMs]);
  const rowById = new Map(filteredRows.map((row) => [row.session.id, row]));
  const localeForTime = locale;

  const createButton = (
    <VButton
      variant="primary"
      icon={<Plus size={15} aria-hidden="true" />}
      className={styles.createButton}
      isPending={createPending}
      isDisabled={createDisabled}
      onPress={onCreate}
    >
      {copy.create}
    </VButton>
  );

  return (
    <main className={styles.root} aria-labelledby="chat-session-browser-title">
      <header className={styles.header}>
        <div className={styles.headingCopy}>
          <span className={styles.eyebrow}>{copy.eyebrow}</span>
          <h1 id="chat-session-browser-title" className={styles.title}>{copy.title}</h1>
          <p className={styles.description}>{copy.description}</p>
        </div>
        {createButton}
      </header>

      <div className={styles.tools}>
        <label className={styles.search}>
          <Search size={16} aria-hidden="true" />
          <VInput
            type="search"
            className={styles.searchInput}
            value={query}
            onChange={(event) => setQuery(event.currentTarget.value)}
            placeholder={copy.search}
            aria-label={copy.search}
            autoComplete="off"
          />
        </label>
        <div className={styles.filters} role="group" aria-label={copy.filterLabel}>
          {filters.map((filter) => (
            <VButton
              key={filter.id}
              variant="ghost"
              aria-pressed={statusFilter === filter.id}
              data-session-status-filter={filter.id}
              className={`${styles.filter}${statusFilter === filter.id ? ` ${styles.filterActive}` : ""}`}
              onPress={() => setStatusFilter(filter.id)}
            >
              {filter.label}
            </VButton>
          ))}
        </div>
      </div>

      {loading && sessions.length === 0 ? (
        <VStateSurface
          tone="loading"
          fill
          title={copy.loading}
          className={styles.state}
        >
          {copy.loadingDescription}
        </VStateSurface>
      ) : error && sessions.length === 0 ? (
        <VStateSurface
          tone="error"
          fill
          role="alert"
          title={copy.errorTitle}
          actions={<VButton variant="secondary" onPress={onRetry}>{copy.retry}</VButton>}
          className={styles.state}
        >
          {error}
        </VStateSurface>
      ) : sessions.length === 0 ? (
        <VStateSurface
          tone="empty"
          fill
          icon={<MessageSquareText size={17} aria-hidden="true" />}
          title={copy.emptyTitle}
          actions={createButton}
          className={styles.state}
        >
          {copy.emptyDescription}
        </VStateSurface>
      ) : (
        <>
          {loading ? (
            <VStateSurface tone="loading" density="compact" title={copy.refreshing} className={styles.inlineState} />
          ) : null}
          {error ? (
            <VStateSurface
              tone="error"
              density="compact"
              title={copy.errorTitle}
              actions={<VButton variant="secondary" onPress={onRetry}>{copy.retry}</VButton>}
              className={styles.inlineState}
            >
              {error}
            </VStateSurface>
          ) : null}
          <div className={styles.resultCount} aria-live="polite">{copy.resultCount(filteredRows.length)}</div>
          {filteredRows.length === 0 ? (
            <VStateSurface
              tone="empty"
              fill
              icon={<SearchX size={17} aria-hidden="true" />}
              title={copy.noMatchesTitle}
              actions={(
                <VButton
                  variant="secondary"
                  onPress={() => { setQuery(""); setStatusFilter("all"); }}
                >
                  {copy.clearFilters}
                </VButton>
              )}
              className={styles.state}
            >
              {copy.noMatchesDescription}
            </VStateSurface>
          ) : (
            <div className={styles.list}>
              {groupedSessions.map((group) => (
                <section
                  key={group.bucket}
                  className={styles.group}
                  aria-label={copy.groups[group.bucket]}
                  data-session-group={group.bucket}
                >
                  <h2 className={styles.groupTitle}>
                    <Clock3 size={13} aria-hidden="true" />
                    {copy.groups[group.bucket]}
                    <span>{group.sessions.length}</span>
                  </h2>
                  <div className={styles.groupRows}>
                    {group.sessions.map((session) => {
                      const row = rowById.get(session.id);
                      if (!row) return null;
                      const active = session.id === activeSessionId;
                      const status = row.tone;
                      const statusText = activityLabel(status, lang);
                      const statusCopy = sessionActivityLabel(status, lang);
                      const avatar = renderAgentAvatar(
                        styles.avatar,
                        row.avatarUrl,
                        row.fallback,
                      );
                      const relativeTime = row.timestamp
                        ? formatRelativeTime(row.timestamp, Date.now(), localeForTime)
                        : lang === "zh" ? "时间未知" : "Unknown time";
                      return (
                        <VButton
                          key={session.id}
                          variant="ghost"
                          contentLayout="plain"
                          aria-current={active ? "page" : undefined}
                          data-session-browser-id={session.id}
                          className={`${styles.row}${active ? ` ${styles.rowActive}` : ""}`}
                          onPress={() => onOpen(session.id)}
                        >
                          {avatar}
                          <span className={styles.rowCopy}>
                            <span className={styles.titleLine}>
                              <span className={styles.sessionTitle}>{session.title || session.id}</span>
                              {row.teamName ? (
                                <span className={styles.teamTag}>
                                  <UsersRound size={11} aria-hidden="true" />
                                  <span>{row.teamName}</span>
                                </span>
                              ) : null}
                            </span>
                            <span className={styles.agentLine}>
                              <span className={styles.agentName}>{row.display.name || copy.unknownAgent}</span>
                              <span aria-hidden="true">·</span>
                              <span>{row.display.modelLabel || copy.unknownModel}</span>
                            </span>
                            <span className={styles.summary}>
                              {row.summary || copy.noActivity}
                            </span>
                            <span className={styles.rowFooter}>
                              <span className={`${styles.status} ${styles[`status_${status}`]}`}>
                                <span className={styles.statusMark} aria-hidden="true" />
                                <span>{statusCopy || statusText}</span>
                              </span>
                              <time className={styles.time} dateTime={row.timestamp || undefined}>{relativeTime}</time>
                            </span>
                          </span>
                        </VButton>
                      );
                    })}
                  </div>
                </section>
              ))}
            </div>
          )}
        </>
      )}
    </main>
  );
}
