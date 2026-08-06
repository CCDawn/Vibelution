import { ExternalLink, Layers3, MessageSquare, Search, ShieldCheck } from "lucide-react";

import type {
  AgentConfigWorkspaceAgent,
  AgentInboxMessage,
  AgentRunHistory,
  AgentRuntimeEvidenceMatch,
} from "../api/types";
import { VButton, VStateSurface, VTooltip } from "../components/vui";
import styles from "./AgentActivityHistoryPanel.styles";
import { ProgressiveRegionSkeleton } from "./shared/ProgressiveRegionSkeleton";

export type AgentActivityTimelineItem = {
  id: string;
  kind: "run" | "sub_run" | "inbox" | "context";
  title: string;
  body: string;
  meta: string;
  timestamp: string;
  sessionId: string;
  messageId: string;
  canOpenLogs: boolean;
  evidence: AgentRuntimeEvidenceMatch | null;
};

export type AgentActivityHistoryPanelCopy = {
  sessions: string;
  logs: string;
  activityPane: string;
  activityTimeline: string;
  loading: string;
  activityTimelineEmpty: string;
  openSession: string;
  openLogs: string;
  focusMessage: string;
  runHistoryTitle: string;
  parentRuns: string;
  subAgentRuns: string;
  maxDepth: string;
  runHistoryLoading: string;
  noRunHistory: string;
  communication: string;
  inboxTitle: string;
  consumeAllMessages: string;
  consumingMessage: string;
  inboxLoading: string;
  consumeMessage: string;
  wakeStatus: string;
  inboxEmpty: string;
};

export type AgentActivityHistoryPanelProps = {
  agent: AgentConfigWorkspaceAgent;
  copy: AgentActivityHistoryPanelCopy;
  lang: "zh" | "en";
  activityTimeline: AgentActivityTimelineItem[];
  isActivityLoading: boolean;
  runHistory: AgentRunHistory | undefined;
  isRunHistoryLoading: boolean;
  inboxMessages: AgentInboxMessage[] | undefined;
  isInboxLoading: boolean;
  inboxPendingCount: number;
  focusedMessageId: string;
  pendingMessageId: string;
  isConsumeAllPending: boolean;
  onOpenSession: (sessionId: string) => void;
  onOpenLogs: (evidence: AgentRuntimeEvidenceMatch | null) => void;
  onFocusMessage: (messageId: string) => void;
  onConsumeAllMessages: () => void;
  onConsumeInboxMessage: (message: AgentInboxMessage) => void;
};

function formatTimestamp(value: string, lang: "zh" | "en") {
  const text = String(value || "").trim();
  if (!text) {
    return "-";
  }
  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) {
    return text;
  }
  return new Intl.DateTimeFormat(lang === "zh" ? "zh-CN" : "en-US", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parsed);
}

function inboxMessageId(message: AgentInboxMessage) {
  return message.messageId || message.eventId;
}

export function AgentActivityHistoryPanel({
  agent,
  copy,
  lang,
  activityTimeline,
  isActivityLoading,
  runHistory,
  isRunHistoryLoading,
  inboxMessages,
  isInboxLoading,
  inboxPendingCount,
  focusedMessageId,
  pendingMessageId,
  isConsumeAllPending,
  onOpenSession,
  onOpenLogs,
  onFocusMessage,
  onConsumeAllMessages,
  onConsumeInboxMessage,
}: AgentActivityHistoryPanelProps) {
  const runCount = runHistory?.runs.length ?? 0;
  const subRunCount = runHistory?.subAgentRuns.length ?? 0;

  return (
    <>
      <section className={styles.detailSection}>
        <div className={styles.panelHeader}>
          <div>
            <p className={styles.panelEyebrow}>{copy.sessions}</p>
            <VTooltip
              width="wide"
              content={(
                <span className={styles.tooltipMeta}>
                  <code>{agent.workspacePath || "-"}</code>
                  <span>{copy.logs}: {formatTimestamp(agent.updatedAt, lang)}</span>
                </span>
              )}
            >
              <h3
                className={styles.metadataTrigger}
                tabIndex={0}
                aria-label={`${agent.directSessionId || "-"}：${agent.workspacePath || "-"}`}
              >
                {agent.directSessionId || "-"}
              </h3>
            </VTooltip>
          </div>
          <MessageSquare size={16} />
        </div>
      </section>

      <section className={styles.detailSection}>
        <div className={styles.panelHeader}>
          <div>
            <p className={styles.panelEyebrow}>{copy.activityPane}</p>
            <h3>{copy.activityTimeline}</h3>
          </div>
          <Layers3 size={16} />
        </div>
        {isActivityLoading ? (
          <ProgressiveRegionSkeleton variant="list" label={copy.loading} />
        ) : activityTimeline.length ? (
          <div className={styles.activityTimelineList}>
            {activityTimeline.map((item) => (
              <article key={item.id} className={`${styles.activityTimelineItem} ${styles[`activityTimelineItem_${item.kind}`]}`}>
                <VTooltip content={item.meta} width="wide">
                  <strong
                    className={styles.metadataTrigger}
                    tabIndex={0}
                    aria-label={`${item.title}：${item.meta}`}
                  >
                    {item.title}
                  </strong>
                </VTooltip>
                <p>{item.body}</p>
                <div className={styles.timelineActions}>
                  {item.sessionId ? (
                    <VButton type="button" variant="ghost" icon={<ExternalLink size={13} />} onPress={() => onOpenSession(item.sessionId)}>
                      {copy.openSession}
                    </VButton>
                  ) : null}
                  {item.canOpenLogs ? (
                    <VButton type="button" variant="ghost" icon={<Search size={13} />} onPress={() => onOpenLogs(item.evidence)}>
                      {item.evidence ? `${copy.openLogs} · ${item.evidence.runtimeSceneId}` : copy.openLogs}
                    </VButton>
                  ) : null}
                  {item.messageId ? (
                    <VButton type="button" variant="ghost" icon={<MessageSquare size={13} />} onPress={() => onFocusMessage(item.messageId)}>
                      {copy.focusMessage}
                    </VButton>
                  ) : null}
                </div>
              </article>
            ))}
          </div>
        ) : (
          <VStateSurface tone="empty" title={copy.activityTimelineEmpty} />
        )}
      </section>

      <section className={styles.detailSection}>
        <div className={styles.panelHeader}>
          <div>
            <p className={styles.panelEyebrow}>{copy.runHistoryTitle}</p>
            <h3>{copy.parentRuns}: {runCount} / {copy.subAgentRuns}: {subRunCount}</h3>
          </div>
          <ShieldCheck size={16} />
        </div>
        {isRunHistoryLoading ? (
          <ProgressiveRegionSkeleton variant="list" label={copy.runHistoryLoading} />
        ) : runCount + subRunCount > 0 ? (
          <div className={styles.runHistoryList}>
            {runHistory?.runs.map((run) => (
              <article key={run.runId} className={styles.runHistoryItem}>
                <VTooltip
                  width="wide"
                  content={`${run.currentPhase || run.sessionId || "-"} · ${formatTimestamp(run.updatedAt || run.startedAt, lang)}`}
                >
                  <strong className={styles.metadataTrigger} tabIndex={0}>
                    {run.status || run.currentPhase || run.runKind}
                  </strong>
                </VTooltip>
                <span>{run.summary || run.runId}</span>
              </article>
            ))}
            {runHistory?.subAgentRuns.map((run) => (
              <article key={run.runId} className={styles.runHistoryItem}>
                <VTooltip
                  width="wide"
                  content={`${run.contextMode || "-"} · ${copy.maxDepth} ${run.depth}/${run.maxDepth} · ${formatTimestamp(run.updatedAt || run.createdAt, lang)}`}
                >
                  <strong className={styles.metadataTrigger} tabIndex={0}>
                    {copy.subAgentRuns} · {run.status || run.currentPhase || run.runKind}
                  </strong>
                </VTooltip>
                <span>{run.summary || run.subRunId || run.runId}</span>
              </article>
            ))}
          </div>
        ) : (
          <VStateSurface tone="empty" title={copy.noRunHistory} />
        )}
      </section>

      <section className={styles.detailSection}>
        <div className={styles.panelHeader}>
          <div>
            <p className={styles.panelEyebrow}>{copy.communication}</p>
            <h3>{copy.inboxTitle}: {inboxPendingCount}</h3>
          </div>
          <div className={styles.panelHeaderActions}>
            <VButton
              type="button"
              variant="secondary"
              isDisabled={inboxPendingCount <= 0 || isConsumeAllPending}
              onPress={onConsumeAllMessages}
            >
              {isConsumeAllPending ? copy.consumingMessage : copy.consumeAllMessages}
            </VButton>
            <MessageSquare size={16} />
          </div>
        </div>
        {isInboxLoading ? (
          <ProgressiveRegionSkeleton variant="list" label={copy.inboxLoading} />
        ) : inboxMessages?.length ? (
          <div className={styles.inboxMessageList}>
            {inboxMessages.map((message) => {
              const messageId = inboxMessageId(message);
              const messagePending = pendingMessageId === messageId;
              return (
                <article
                  key={messageId}
                  className={focusedMessageId === messageId ? `${styles.inboxMessageItem} ${styles.inboxMessageItemFocused}` : styles.inboxMessageItem}
                >
                  <div className={styles.inboxMessageTop}>
                    <VTooltip
                      width="wide"
                      content={(
                        <span className={styles.tooltipMeta}>
                          <span>{formatTimestamp(message.createdAt, lang)} · {message.kind || "agent_message"}</span>
                          <span>{copy.wakeStatus}: {message.delivery?.wakeStatus || "pending"} · thread {message.threadId || "-"}</span>
                        </span>
                      )}
                    >
                      <span
                        className={styles.metadataTrigger}
                        tabIndex={0}
                        aria-label={`${message.sourceAgentName || message.sourceAgentCode || message.sourceAgentId || "-"}：${copy.wakeStatus} ${message.delivery?.wakeStatus || "pending"}`}
                      >
                        <strong>{message.sourceAgentName || message.sourceAgentCode || message.sourceAgentId || "-"}</strong>
                      </span>
                    </VTooltip>
                    <VButton
                      type="button"
                      variant="secondary"
                      isDisabled={messagePending}
                      onPress={() => onConsumeInboxMessage(message)}
                    >
                      {messagePending ? copy.consumingMessage : copy.consumeMessage}
                    </VButton>
                  </div>
                  <p>{message.summary || message.content || message.threadId || messageId}</p>
                </article>
              );
            })}
          </div>
        ) : (
          <VStateSurface tone="empty" title={copy.inboxEmpty} />
        )}
      </section>
    </>
  );
}
