import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BellRing, ExternalLink, Megaphone, RefreshCw } from "lucide-react";

import { queryKeys } from "../../api/queryKeys";
import {
  isProjectAgentBusEventRevoked,
  listProjectAgentBusTimeline,
  sendProjectAgentBusMessage,
} from "../../api/projectAgentBus";
import type { ProjectAgentBusEvent, ProjectAgentBusTimeline } from "../../api/types";
import { agentBroadcastEventTimeMs } from "../../app/agentBroadcastBadge";
import { VButton, VDialog, VEmptyState, VPanelHeader, VStateSurface, VTextarea } from "../../components/vui";
import { CHAT_SECONDARY_PROJECT_BUS_POLL_MS } from "../chatSecondaryPollPolicy";
import styles from "./ProjectNotificationsPanel.styles";

export type ProjectNotificationsPanelProps = {
  lang: "zh" | "en";
  onOpenSession?: (sessionId: string) => void;
  onExpand?: () => void;
  onSeen?: (latestEventMs: number) => void;
};

function noticeTime(value: string, lang: "zh" | "en") {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value || "—";
  }
  return new Intl.DateTimeFormat(lang === "zh" ? "zh-CN" : "en-US", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function eventTypeLabel(event: ProjectAgentBusEvent, lang: "zh" | "en") {
  if (event.messageType === "agent_broadcast") {
    return lang === "zh" ? "助手通知" : "Agent notice";
  }
  if (event.messageType === "project_observation") {
    return lang === "zh" ? "项目观察" : "Project observation";
  }
  if (event.messageType === "user_guidance") {
    return lang === "zh" ? "项目广播" : "Project broadcast";
  }
  if (event.messageType === "agent_private") {
    return lang === "zh" ? "助手消息" : "Agent message";
  }
  return event.messageType;
}

function eventTargetLabel(event: ProjectAgentBusEvent, lang: "zh" | "en") {
  if (event.targetScope === "all") {
    return lang === "zh" ? "全体 Agent" : "All agents";
  }
  if (event.targetAgentNames.length) {
    const names = event.targetAgentNames.slice(0, 2).join("、");
    return event.targetAgentNames.length > 2
      ? `${names} +${event.targetAgentNames.length - 2}`
      : names;
  }
  return event.targetScope === "observe"
    ? (lang === "zh" ? "观察通知" : "Observation")
    : (lang === "zh" ? "项目成员" : "Project agents");
}

function relatedSessions(event: ProjectAgentBusEvent) {
  const seen = new Set<string>();
  const sessions: Array<{ sessionId: string; agentName: string }> = [];
  for (const target of [...event.deliveries, ...event.interruptions]) {
    const sessionId = String(target.targetSessionId ?? "").trim();
    if (!sessionId || seen.has(sessionId)) {
      continue;
    }
    seen.add(sessionId);
    sessions.push({ sessionId, agentName: String(target.targetAgentName ?? "").trim() });
  }
  return sessions;
}

function latestEventMs(timeline: ProjectAgentBusTimeline | undefined) {
  const events = timeline?.events ?? [];
  return agentBroadcastEventTimeMs(events[events.length - 1]);
}

function ProjectNotice({
  event,
  lang,
  onOpenSession,
}: {
  event: ProjectAgentBusEvent;
  lang: "zh" | "en";
  onOpenSession?: (sessionId: string) => void;
}) {
  const revoked = isProjectAgentBusEventRevoked(event);
  const linkedSessions = onOpenSession ? relatedSessions(event) : [];
  const visibleSessions = linkedSessions.slice(0, 2);
  const actor = event.createdBy === "user"
    ? (lang === "zh" ? "你" : "You")
    : (event.createdBy || (lang === "zh" ? "未知助手" : "Unknown Agent"));
  const body = revoked
    ? (lang === "zh" ? "这条消息已撤回。" : "This message was recalled.")
    : (String(event.summary ?? "").trim() || String(event.content ?? ""));

  return (
    <article
      className={revoked ? `${styles.event} ${styles.eventRevoked}` : styles.event}
      data-event-id={event.eventId}
    >
      <div className={styles.eventHeader}>
        <div className={styles.eventHeading}>
          <strong className={styles.actor}>{actor}</strong>
          <span className={styles.type}>{eventTypeLabel(event, lang)}</span>
        </div>
        <time className={styles.time} dateTime={event.createdAt}>{noticeTime(event.createdAt, lang)}</time>
      </div>
      <p className={styles.content}>{body}</p>
      <div className={styles.meta}>
        <span>{eventTargetLabel(event, lang)}</span>
        {event.deliveries.length ? (
          <span>{event.deliveries.length} {lang === "zh" ? "次投递" : "deliveries"}</span>
        ) : null}
        {event.kernel?.taskId ? (
          <span>{lang === "zh" ? "关联 Kernel 任务" : "Linked Kernel task"}</span>
        ) : null}
      </div>
      {visibleSessions.length ? (
        <div className={styles.sessions}>
          {visibleSessions.map((session, index) => {
            const label = session.agentName
              ? (lang === "zh" ? `打开 ${session.agentName}` : `Open ${session.agentName}`)
              : (lang === "zh" ? `打开会话 ${index + 1}` : `Open session ${index + 1}`);
            return (
              <VButton
                key={session.sessionId}
                type="button"
                variant="ghost"
                density="compact"
                icon={<ExternalLink size={12} aria-hidden="true" />}
                className={styles.sessionButton}
                aria-label={label}
                onPress={() => onOpenSession?.(session.sessionId)}
              >
                {label}
              </VButton>
            );
          })}
          {linkedSessions.length > visibleSessions.length ? (
            <span className={styles.sessionOverflow}>
              +{linkedSessions.length - visibleSessions.length}
            </span>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

export function ProjectNotificationsPanel({
  lang,
  onOpenSession,
  onExpand,
  onSeen,
}: ProjectNotificationsPanelProps) {
  const queryClient = useQueryClient();
  const [broadcastOpen, setBroadcastOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const lastReportedMsRef = useRef(0);
  const timelineQuery = useQuery({
    queryKey: queryKeys.projectAgentBus(),
    queryFn: ({ signal }) => listProjectAgentBusTimeline(undefined, { signal }),
    refetchInterval: CHAT_SECONDARY_PROJECT_BUS_POLL_MS,
  });
  const sendMutation = useMutation({
    mutationFn: ({ content }: { content: string }) => sendProjectAgentBusMessage({ content }),
    onSuccess: () => {
      setDraft("");
      setBroadcastOpen(false);
      void queryClient.invalidateQueries({ queryKey: queryKeys.projectAgentBus() });
    },
  });

  const events = timelineQuery.data?.events ?? [];
  const newestEventMs = latestEventMs(timelineQuery.data);

  useEffect(() => {
    if (!timelineQuery.isSuccess || newestEventMs <= 0 || newestEventMs <= lastReportedMsRef.current || !onSeen) {
      return;
    }
    // This effect runs after the successful event list has committed to the DOM.
    lastReportedMsRef.current = newestEventMs;
    onSeen(newestEventMs);
  }, [newestEventMs, onSeen, timelineQuery.dataUpdatedAt, timelineQuery.isSuccess]);

  const labels = lang === "zh"
    ? {
        title: "通知",
        send: "发广播",
        refresh: "刷新通知",
        expand: "完整视图",
        loading: "正在加载通知",
        loadError: "通知加载失败，请重试。",
        retry: "重试",
        emptyTitle: "暂时没有通知",
        emptyDescription: "项目广播和助手消息会显示在这里。",
        dialogTitle: "发送项目广播",
        dialogDescription: "向项目中的 Agent 发送一条广播。此操作不会请求中断目标 Agent。",
        inputLabel: "广播内容",
        placeholder: "写下要发送的内容…",
        cancel: "取消",
        submit: "发送广播",
        submitting: "正在发送…",
        sendError: "广播发送失败，请重试。",
      }
    : {
        title: "Notices",
        send: "Broadcast",
        refresh: "Refresh notices",
        expand: "Full view",
        loading: "Loading notices",
        loadError: "Could not load notices. Try again.",
        retry: "Retry",
        emptyTitle: "No notices yet",
        emptyDescription: "Project broadcasts and Agent messages will appear here.",
        dialogTitle: "Send project broadcast",
        dialogDescription: "Send a broadcast to project Agents. This does not request interruption of target Agents.",
        inputLabel: "Broadcast content",
        placeholder: "Write a message…",
        cancel: "Cancel",
        submit: "Send broadcast",
        submitting: "Sending…",
        sendError: "Could not send the broadcast. Try again.",
      };

  function handleBroadcastOpenChange(open: boolean) {
    if (!open && sendMutation.isPending) {
      return;
    }
    setBroadcastOpen(open);
    if (open) {
      setDraft("");
      sendMutation.reset();
    }
  }

  function handleSendBroadcast() {
    const content = draft.trim();
    if (!content || sendMutation.isPending) {
      return;
    }
    // The API defaults interruptTargets to false; no interrupt control is exposed here.
    sendMutation.mutate({ content });
  }

  const body = timelineQuery.isPending && !timelineQuery.data ? (
    <VStateSurface
      tone="loading"
      density="compact"
      title={labels.loading}
      className={styles.loading}
      data-testid="project-notifications-loading"
    />
  ) : timelineQuery.isError && !timelineQuery.data ? (
    <VStateSurface
      tone="error"
      density="compact"
      title={labels.loadError}
      className={styles.loading}
      actions={(
        <VButton type="button" variant="secondary" onPress={() => { void timelineQuery.refetch(); }}>
          {labels.retry}
        </VButton>
      )}
      role="alert"
      data-testid="project-notifications-error"
    />
  ) : events.length ? (
    <div className={styles.eventList} aria-live="polite">
      {[...events].reverse().slice(0, 40).map((event) => (
        <ProjectNotice
          key={event.eventId}
          event={event}
          lang={lang}
          onOpenSession={onOpenSession}
        />
      ))}
    </div>
  ) : (
    <div className={styles.empty}>
      <VEmptyState
        align="start"
        icon={<BellRing size={18} aria-hidden="true" />}
        title={labels.emptyTitle}
        className={styles.emptyState}
      >
        {labels.emptyDescription}
      </VEmptyState>
    </div>
  );

  return (
    <section className={styles.root} aria-label={labels.title} data-testid="project-notifications-panel">
      <header className={styles.header}>
        <VPanelHeader title={labels.title} headingLevel={3} className={styles.heading} />
        <div className={styles.headerActions}>
          <VButton
            type="button"
            variant="ghost"
            density="compact"
            icon={<RefreshCw size={14} aria-hidden="true" />}
            aria-label={labels.refresh}
            title={labels.refresh}
            isDisabled={timelineQuery.isFetching}
            onPress={() => { void timelineQuery.refetch(); }}
          >
            {lang === "zh" ? "刷新" : "Refresh"}
          </VButton>
          {onExpand ? (
            <VButton type="button" variant="ghost" density="compact" onPress={onExpand}>
              {labels.expand}
            </VButton>
          ) : null}
          <VButton
            type="button"
            variant="secondary"
            density="compact"
            icon={<Megaphone size={14} aria-hidden="true" />}
            onPress={() => handleBroadcastOpenChange(true)}
          >
            {labels.send}
          </VButton>
        </div>
      </header>

      <div className={styles.body}>
        {timelineQuery.isError && timelineQuery.data ? (
          <div className={styles.error} role="alert">
            <span>{labels.loadError}</span>
            <VButton type="button" variant="ghost" density="compact" onPress={() => { void timelineQuery.refetch(); }}>
              {labels.retry}
            </VButton>
          </div>
        ) : null}
        {body}
      </div>

      <VDialog
        open={broadcastOpen}
        onOpenChange={handleBroadcastOpenChange}
        title={labels.dialogTitle}
        description={labels.dialogDescription}
        size="sm"
        footer={(
          <>
            <VButton
              type="button"
              variant="secondary"
              isDisabled={sendMutation.isPending}
              onPress={() => setBroadcastOpen(false)}
            >
              {labels.cancel}
            </VButton>
            <VButton
              type="button"
              variant="primary"
              icon={<Megaphone size={14} aria-hidden="true" />}
              isPending={sendMutation.isPending}
              isDisabled={!draft.trim() || sendMutation.isPending}
              onPress={() => handleSendBroadcast()}
            >
              {sendMutation.isPending ? labels.submitting : labels.submit}
            </VButton>
          </>
        )}
      >
        <div className={styles.dialogForm}>
          <label className={styles.dialogFieldLabel}>
            <span>{labels.inputLabel}</span>
            <VTextarea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              minRows={4}
              maxLength={4_000}
              placeholder={labels.placeholder}
              isDisabled={sendMutation.isPending}
            />
          </label>
          {sendMutation.isError ? (
            <p className={styles.dialogError} role="alert">{labels.sendError}</p>
          ) : null}
        </div>
      </VDialog>
    </section>
  );
}
