import { useEffect, useId, useRef, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

import type {
  ChatRoomMessage,
  ChatRoomParticipant,
  ChatRoomSpeakerProgress,
} from "../../api/types";
import { VButton, VStateRow } from "../../components/vui";
import type { ChatMentionTarget } from "../chatMentionTokens";
import { ConversationStreamingResponseContent } from "../../components/conversation/ConversationStreamingResponseContent";
import { LazyConversationMarkdownRenderer } from "../../components/conversation/LazyConversationMarkdownRenderer";
import { ChatGroupMessageBody, ChatMentionedText } from "./ChatGroupMessagePresentation";
import messageStyles from "./ChatGroupMessagePresentation.styles";
import { ChatMessageChromeHeader } from "./ChatMessageChromeHeader";
import {
  chatRoomModeLabel,
  chatRoomPurposeLabel,
  groupConsecutiveBy,
  shouldCollapseGroupMessage,
} from "./chatRoutePresentation";
import type {
  GroupSpeakerProgressMap,
  GroupSpeakerStreamEntry,
  GroupSpeakerStreamMap,
} from "./useGroupRoomStream";
import type {
  GroupTimelineArtifactRow,
  GroupTimelineItem,
  GroupTimelineMemberChangeRow,
} from "./useGroupRoomTimeline";
import type { ChatGroupCenterSurfaceProps } from "./ChatGroupCenterSurface";
import styles from "./ChatGroupRoundsTimeline.styles";

const GROUP_TYPING_STALE_AFTER_MS = 150_000;
const GROUP_TYPING_STALE_TICK_MS = 15_000;

// The room service's delivery counters are useful diagnostics, but are not
// a discussion conclusion. Keep them available behind the round result.
function isDeliverySummary(summary: string) {
  return /^本轮群聊完成：\d+\/\d+ 位参与者成功发言/.test(summary.trim())
    || /^Chat room round finished: \d+\/\d+ participants responded successfully;/.test(summary.trim());
}

function useStalenessNow(enabled: boolean): number {
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    if (!enabled) return;
    setNowMs(Date.now());
    const timer = window.setInterval(() => setNowMs(Date.now()), GROUP_TYPING_STALE_TICK_MS);
    return () => window.clearInterval(timer);
  }, [enabled]);
  return nowMs;
}


function GroupMemberChangeRow({
  row,
  lang,
  formatTime,
  activeGroupParticipantById,
  groupParticipantIdentity,
}: {
  row: GroupTimelineMemberChangeRow;
  lang: "zh" | "en";
  formatTime: (value: string) => string;
  activeGroupParticipantById: Map<string, ChatRoomParticipant>;
  groupParticipantIdentity: ChatGroupCenterSurfaceProps["groupParticipantIdentity"];
}) {
  const describe = (participantIds: string[]) =>
    participantIds.map((participantId) => {
      const participant = activeGroupParticipantById.get(participantId);
      return groupParticipantIdentity(participant, { participantId }).identityLabel;
    });
  const addedNames = describe(row.addedParticipantIds);
  const removedNames = describe(row.removedParticipantIds);
  const parts: string[] = [];
  if (addedNames.length) {
    parts.push(lang === "zh" ? `成员加入：${addedNames.join("、")}` : `Joined: ${addedNames.join(", ")}`);
  }
  if (removedNames.length) {
    parts.push(lang === "zh" ? `成员退出：${removedNames.join("、")}` : `Left: ${removedNames.join(", ")}`);
  }
  if (!parts.length) return null;
  return (
    <div className={styles.groupRoundDivider} data-group-member-change={row.key}>
      <span>{parts.join(lang === "zh" ? "；" : "; ")}</span>
      <time>{formatTime(row.createdAt)}</time>
    </div>
  );
}

function GroupArtifactChangeRow({
  row,
  lang,
  formatTime,
  onOpenArtifacts,
}: {
  row: GroupTimelineArtifactRow;
  lang: "zh" | "en";
  formatTime: (value: string) => string;
  onOpenArtifacts?: (taskIds: string[], trigger: HTMLElement) => void;
}) {
  const separator = lang === "zh" ? "、" : ", ";
  const pathSummary = row.changedPaths.slice(0, 3).join(separator);
  const detail = pathSummary
    ? (lang === "zh" ? `：${pathSummary}${row.changedPathsTruncated ? "…" : ""}` : `: ${pathSummary}${row.changedPathsTruncated ? "…" : ""}`)
    : "";
  return (
    <div className={styles.groupRoundDivider} data-group-artifact-change={row.key}>
      <span>
        {lang === "zh" ? `交付了 ${row.fileCount} 个文件变更${detail}` : `Delivered ${row.fileCount} file changes${detail}`}
      </span>
      <time>{formatTime(row.createdAt)}</time>
      {onOpenArtifacts && row.taskIds?.length ? (
        <VButton variant="ghost" onClick={(event) => onOpenArtifacts(row.taskIds!, event.currentTarget)}>
          {lang === "zh" ? "查看改动" : "View changes"}
        </VButton>
      ) : null}
    </div>
  );
}

export function GroupRoundsTimeline({
  items,
  purposeFallback,
  userDisplayName,
  lang,
  formatTime,
  statusLabel,
  activeGroupParticipantById,
  groupParticipantIdentity,
  renderAgentAvatar,
  avatarInitials,
  expandedGroupMessageIds,
  chatMentionTargets,
  groupStreamConnected,
  groupSpeakerStreams,
  groupSpeakerProgress,
  onOpenMentionTarget,
  onToggleExpandedGroupMessage,
  workspaceRoot,
  onOpenRailFile,
  onOpenArtifacts,
}: {
  items: GroupTimelineItem[];
  purposeFallback: string;
  userDisplayName: string;
  lang: "zh" | "en";
  formatTime: (value: string) => string;
  statusLabel: (value: string) => string;
  activeGroupParticipantById: Map<string, ChatRoomParticipant>;
  groupParticipantIdentity: ChatGroupCenterSurfaceProps["groupParticipantIdentity"];
  renderAgentAvatar: ChatGroupCenterSurfaceProps["renderAgentAvatar"];
  avatarInitials: ChatGroupCenterSurfaceProps["avatarInitials"];
  expandedGroupMessageIds: string[];
  chatMentionTargets: ChatMentionTarget[];
  groupStreamConnected?: boolean;
  groupSpeakerStreams?: GroupSpeakerStreamMap;
  groupSpeakerProgress?: GroupSpeakerProgressMap;
  onOpenMentionTarget: (target: ChatMentionTarget) => void;
  onToggleExpandedGroupMessage: (messageId: string) => void;
  workspaceRoot?: string;
  onOpenRailFile?: (path: string) => void;
  onOpenArtifacts?: (taskIds: string[], trigger: HTMLElement) => void;
}) {
  const transcriptPrefix = useId();
  const [expandedResults, setExpandedResults] = useState<Record<string, boolean>>({});
  const roundElements = useRef(new Map<string, HTMLElement>());
  const revealFailedMessage = (roundId: string) => {
    requestAnimationFrame(() => {
      const message = roundElements.current.get(roundId)?.querySelector<HTMLElement>('[data-parse-invalid="true"]');
      message?.scrollIntoView({ block: "center", behavior: "smooth" });
      message?.focus({ preventScroll: true });
    });
  };
  const viewRounds = items.flatMap((item) => (item.kind === "round" ? [item.round] : []));
  const hasRunningSpeaker = viewRounds.some((round) => {
    if (String(round.status ?? "").trim().toLowerCase() !== "running") return false;
    const delivered = new Set(
      (round.messages ?? []).map((message) => String(message.participantId ?? "").trim()),
    );
    const pendingIds = (round.speakerOrder ?? [])
      .map((participantId) => String(participantId ?? "").trim())
      .filter((participantId) => participantId && !delivered.has(participantId));
    return pendingIds.some((participantId, index) => {
      const progress = groupSpeakerProgress?.[round.roundId]?.[participantId]
        ?? round.speakerProgress?.find((item) => item.participantId === participantId);
      return progress ? progress.state === "running" : index === 0;
    });
  });
  const stalenessNowMs = useStalenessNow(hasRunningSpeaker);
  return (
    <>
      {items.map((item, itemIndex) => {
        if (item.kind === "member_change") {
          return (
            <GroupMemberChangeRow
              key={item.row.key}
              row={item.row}
              lang={lang}
              formatTime={formatTime}
              activeGroupParticipantById={activeGroupParticipantById}
              groupParticipantIdentity={groupParticipantIdentity}
            />
          );
        }
        if (item.kind === "artifact") {
          return (
            <GroupArtifactChangeRow
              key={item.row.key}
              row={item.row}
              lang={lang}
              formatTime={formatTime}
              onOpenArtifacts={onOpenArtifacts}
            />
          );
        }
        const round = item.round;
        // Ordinal among round sections only, so member-change rows never
        // shift the 「第 N 轮」 numbering.
        const roundIndex = items
          .slice(0, itemIndex)
          .filter((previous) => previous.kind === "round")
          .length;
        const roundRunning = String(round.status ?? "").trim().toLowerCase() === "running";
        const transcriptId = `${transcriptPrefix}-${round.roundId}`;
        const deliverySummary = isDeliverySummary(round.summary || "");
        const resultOpen = expandedResults[round.roundId] ?? false;
        const challengeMessages = (round.messages ?? []).filter(
          (message) => message.messagePayload?.kind === "challenge_meeting_message",
        );
        const parsedCount = challengeMessages.filter(
          (message) => message.messagePayload?.audit?.parseStatus === "structured",
        ).length;
        const invalidCount = challengeMessages.filter(
          (message) => message.messagePayload?.audit?.parseStatus === "invalid",
        ).length;
        const deliveredParticipantIds = new Set(
          (round.messages ?? []).map((message) => String(message.participantId ?? "").trim()),
        );
        const pendingSpeakerIds = (round.speakerOrder ?? [])
          .map((participantId) => String(participantId ?? "").trim())
          .filter((participantId) => participantId && !deliveredParticipantIds.has(participantId));
        return (
          <section key={round.roundId} data-group-round-id={round.roundId} className={styles.groupRoundBlock} ref={(element) => {
            if (element) roundElements.current.set(round.roundId, element);
            else roundElements.current.delete(round.roundId);
          }}>
            <div className={styles.groupRoundDivider}>
              <span title={`${chatRoomModeLabel({ id: round.mode, label: round.mode, status: "active" }, lang)} · ${chatRoomPurposeLabel({ id: round.purpose ?? purposeFallback, label: round.purpose ?? purposeFallback }, lang)}`}>
                {lang === "zh" ? `第 ${roundIndex + 1} 轮` : `Round ${roundIndex + 1}`}
                {" · "}
                {round.status === "completed" ? (lang === "zh" ? "发言已结束" : "Speaking finished") : statusLabel(round.status)}
              </span>
              <time>{formatTime(round.updatedAt || round.startedAt)}</time>
            </div>
            {invalidCount > 0 && !roundRunning ? (
              <VStateRow tone="danger" role="status">
                {lang === "zh" ? `本轮结果待处理：${parsedCount}/${challengeMessages.length} 条科研发言解析成功，${invalidCount} 条解析失败。` : `Round needs attention: ${parsedCount}/${challengeMessages.length} research messages parsed, ${invalidCount} failed.`}
              </VStateRow>
            ) : null}
            {invalidCount > 0 ? <div className={styles.groupRoundActions}>
              <VButton variant="secondary" onClick={() => revealFailedMessage(round.roundId)}>
                {lang === "zh" ? "定位解析失败发言" : "Find failed message"}
              </VButton>
            </div> : null}
            <div id={transcriptId}>
            <article className={styles.groupTopicMessage}>
              <div className={styles.groupTopicBubble}>
                <div className={styles.groupStreamIdentity} data-testid="group-stream-topic-identity">
                  {renderAgentAvatar(
                    styles.groupBubbleAvatar,
                    undefined,
                    avatarInitials("", userDisplayName, lang === "zh" ? "你" : "You"),
                  )}
                  <span className={styles.groupStreamName}>{userDisplayName}</span>
                </div>
                <p className={styles.groupStreamCopy}>
                  <ChatMentionedText
                    content={round.topic}
                    lang={lang}
                    mentionTargets={chatMentionTargets}
                    onOpenMentionTarget={onOpenMentionTarget}
                  />
                </p>
              </div>
            </article>
            <div className={styles.groupMessageList}>
              {groupConsecutiveBy(
                round.messages ?? [],
                (message: ChatRoomMessage) => String(message.participantId ?? "").trim(),
              ).map((cluster) => (
                <div key={cluster[0].messageId} className={styles.groupStreamCluster}>
                  {cluster.map((message: ChatRoomMessage, index) => {
                    const speakerParticipant = activeGroupParticipantById.get(String(message.participantId ?? "").trim());
                    const speakerIdentity = groupParticipantIdentity(speakerParticipant, {
                      agentId: message.agentId,
                      agentCode: message.speakerCode,
                      title: message.speakerTitle,
                      participantId: message.participantId,
                    });
                    const showIdentity = index === 0;
                    const messageTime = formatTime(message.timestamp || round.updatedAt);
                    return (
                      <article
                        key={message.messageId}
                        tabIndex={-1}
                        data-parse-invalid={message.messagePayload?.kind === "challenge_meeting_message" && message.messagePayload.audit?.parseStatus === "invalid" ? "true" : undefined}
                        className={
                          message.status === "failed"
                            ? `${styles.groupBubbleRow} ${styles.groupBubbleRowFailed}`
                            : styles.groupBubbleRow
                        }
                      >
                        {showIdentity ? (
                          <div className={styles.groupStreamIdentity} data-testid="group-stream-identity">
                            {renderAgentAvatar(
                              styles.groupBubbleAvatar,
                              speakerIdentity.avatarImageUrl || undefined,
                              avatarInitials(message.speakerCode, speakerIdentity.name, "AI"),
                            )}
                            <ChatMessageChromeHeader
                              className={styles.groupBubbleHeader}
                              density="bubble"
                              title={(
                                <strong className={styles.groupStreamName} title={speakerIdentity.fullIdentityLabel}>
                                  {speakerIdentity.identityLabel}
                                </strong>
                              )}
                              trailing={(
                                <>
                                  {message.status !== "completed" ? <span>{statusLabel(message.status)}</span> : null}
                                  <time className={styles.groupBubbleMeta}>{messageTime}</time>
                                </>
                              )}
                            />
                          </div>
                        ) : null}
                        <div className={styles.groupStreamCopy}>
                          <ChatGroupMessageBody
                            message={message}
                            identityName={speakerIdentity.name}
                            lang={lang}
                            expandedMessageIds={expandedGroupMessageIds}
                            mentionTargets={chatMentionTargets}
                            onOpenMentionTarget={onOpenMentionTarget}
                            onToggleExpanded={onToggleExpandedGroupMessage}
                            workspaceRoot={workspaceRoot}
                            onOpenRailFile={onOpenRailFile}
                          />
                        </div>
                      </article>
                    );
                  })}
                </div>
              ))}
              {roundRunning ? pendingSpeakerIds.map((participantId, index) => {
                const participant = activeGroupParticipantById.get(participantId);
                if (!participant) return null;
                const progress: ChatRoomSpeakerProgress = groupSpeakerProgress?.[round.roundId]?.[participantId]
                  ?? round.speakerProgress?.find((item) => item.participantId === participantId)
                  ?? {
                    participantId,
                    sessionId: participant.sessionId,
                    state: index === 0 ? "running" : "queued",
                    status: "",
                    updatedAt: round.updatedAt || round.startedAt || "",
                  };
                const speakerStream: GroupSpeakerStreamEntry | undefined =
                  groupSpeakerStreams?.[String(round.roundId || "")]?.[participantId];
                const progressUpdatedAtMs = Date.parse(progress.updatedAt || "");
                const lastDeltaAtMs = speakerStream?.lastDeltaAtMs ?? 0;
                const hasProgressUpdatedAt = Number.isFinite(progressUpdatedAtMs);
                const lastActivityMs = Math.max(
                  hasProgressUpdatedAt ? progressUpdatedAtMs : 0,
                  lastDeltaAtMs,
                );
                const hasActivityClock = hasProgressUpdatedAt || lastDeltaAtMs > 0;
                const typingStale = progress.state === "running"
                  && (!hasActivityClock || stalenessNowMs - lastActivityMs > GROUP_TYPING_STALE_AFTER_MS);
                const streamText = progress.state === "running" && typeof speakerStream?.content === "string"
                  ? speakerStream.content
                  : "";
                const hasStreamText = streamText.trim().length > 0;
                const identity = groupParticipantIdentity(participant);
                const staleCopy = groupStreamConnected === false
                  ? (lang === "zh"
                    ? "实时连接已断开，正在重连，已暂停输入状态显示。"
                    : "Live connection lost; reconnecting. Typing status paused.")
                  : (lang === "zh"
                    ? "该发言已等待较久，仍在等待后端响应…"
                    : "This speaker has been waiting a while; still waiting for the backend…");
                const waitingForPrefix = index > 0;
                const settledBase = lang === "zh"
                  ? (({ failed: "发言失败", blocked: "已阻止", stopped: "已停止", partial: "部分完成" } as Record<string, string>)[progress.status] ?? "已完成")
                  : (({ failed: "failed", blocked: "blocked", stopped: "stopped", partial: "partially complete" } as Record<string, string>)[progress.status] ?? "complete");
                const settledLabel = `${settledBase}${waitingForPrefix
                  ? (lang === "zh" ? "，等待前序发言" : "; waiting for earlier speaker")
                  : ""}`;
                const trailingLabel = progress.state === "settled"
                  ? settledLabel
                  : progress.state === "queued"
                    ? (lang === "zh" ? "等待发言" : "queued")
                    : typingStale
                      ? (lang === "zh" ? "等待中" : "waiting")
                      : (lang === "zh" ? "正在输入" : "typing");
                return (
                  <article
                    key={`progress:${round.roundId}:${participantId}`}
                    className={`${styles.groupBubbleRow} ${styles.groupBubbleRowPending}`}
                  >
                    <div className={styles.groupStreamIdentity} data-testid="group-stream-identity">
                      {renderAgentAvatar(
                        styles.groupBubbleAvatar,
                        identity.avatarImageUrl || undefined,
                        avatarInitials(participant.agentCode, identity.name, "AI"),
                      )}
                      <ChatMessageChromeHeader
                        className={styles.groupBubbleHeader}
                        density="bubble"
                        title={(
                          <strong className={styles.groupStreamName} title={identity.fullIdentityLabel}>
                            {identity.identityLabel}
                          </strong>
                        )}
                        trailing={<span>{trailingLabel}</span>}
                      />
                    </div>
                    {hasStreamText ? (() => {
                      // Ordinary-chat parity: stable prefix stays memoized, only the
                      // live tail re-parses per delta; mentions resolve on settle.
                      // The long-message collapse rule from settled bubbles still applies.
                      const streamMessageId = `streaming:${round.roundId}:${participantId}`;
                      const streamExpanded = expandedGroupMessageIds.includes(streamMessageId);
                      const streamCollapsed = shouldCollapseGroupMessage(streamText) && !streamExpanded;
                      return (
                        <>
                          <div className={streamCollapsed
                            ? `${styles.groupStreamCopy} ${messageStyles.groupBubbleBodyCollapsed}`
                            : styles.groupStreamCopy}>
                            <ConversationStreamingResponseContent
                              content={streamText}
                              isStreaming
                              workspaceRoot={workspaceRoot}
                              language={lang}
                              onOpenRailFile={onOpenRailFile}
                            />
                          </div>
                          {streamCollapsed || streamExpanded ? (
                            <VButton
                              type="button"
                              className={messageStyles.groupBubbleToggle}
                              aria-expanded={streamExpanded}
                              onClick={() => onToggleExpandedGroupMessage(streamMessageId)}
                            >
                              {streamExpanded ? (lang === "zh" ? "收起" : "Collapse") : (lang === "zh" ? "展开全文" : "Show full")}
                            </VButton>
                          ) : null}
                        </>
                      );
                    })() : progress.state === "running" && typingStale ? (
                      <div className={styles.groupStreamCopy}>
                        <p className={styles.groupTypingStaleNote} role="status">{staleCopy}</p>
                      </div>
                    ) : progress.state === "running" ? (
                      <div
                        className={`${styles.groupStreamCopy} ${styles.groupTypingDots}`}
                        aria-label={lang === "zh" ? "正在输入" : "Typing"}
                      >
                        <span />
                        <span />
                        <span />
                      </div>
                    ) : null}
                    {hasStreamText && typingStale ? (
                      <div className={styles.groupStreamCopy}>
                        <p className={styles.groupTypingStaleNote} role="status">{staleCopy}</p>
                      </div>
                    ) : null}
                  </article>
                );
              }) : null}
            </div>
            </div>
            {round.summary && !roundRunning && invalidCount === 0 ? deliverySummary ? (
              <div className={styles.groupRoundResult}>
                <VButton variant="ghost" className={styles.groupResultToggle} aria-expanded={resultOpen} aria-controls={`${transcriptId}-result`}
                  icon={resultOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                  onClick={() => setExpandedResults((current) => ({ ...current, [round.roundId]: !resultOpen }))}>
                  {lang === "zh" ? "轮次结果" : "Round result"}
                </VButton>
                {resultOpen ? (
                  <div id={`${transcriptId}-result`} className={styles.groupResultCopy}>
                    <LazyConversationMarkdownRenderer content={round.summary} language={lang} />
                  </div>
                ) : null}
              </div>
            ) : (
              <article className={styles.groupRoundSummary}>
                <strong>{lang === "zh" ? "本轮结论" : "Round conclusion"}</strong>
                <LazyConversationMarkdownRenderer content={round.summary} language={lang} />
              </article>
            ) : null}
          </section>
        );
      })}
    </>
  );
}

/**
 * Center surface for project-agent-bus notice stream and standard group room chat.
 */
