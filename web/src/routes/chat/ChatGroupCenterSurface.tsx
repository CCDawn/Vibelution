import { BellRing, Square, UsersRound } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { kernelTaskCenterHref } from "../../api/kernel";
import { isProjectAgentBusEventRevoked } from "../../api/projectAgentBus";
import type {
  ChatRoomDetail,
  ChatRoomMessage,
  ChatRoomParticipant,
  ChatRoomSpeakerProgress,
  ProjectAgentBusEvent,
  ProjectAgentBusTimeline,
} from "../../api/types";
import { VButton, VContextualHint, VNativeInput } from "../../components/vui";
import type { ChatMentionTarget } from "../chatMentionTokens";
import { ProgressiveRegionSkeleton } from "../shared/ProgressiveRegionSkeleton";
import styles from "./ChatGroupCenterSurface.styles";
import { ChatGroupMessageBody, ChatMentionedText } from "./ChatGroupMessagePresentation";
import { ChatMessageChromeHeader } from "./ChatMessageChromeHeader";
import { groupConsecutiveBy } from "./chatRoutePresentation";
import type { GroupSpeakerProgressMap, GroupSpeakerStreamEntry, GroupSpeakerStreamMap } from "./useGroupRoomStream";

// The backend only publishes a full snapshot when a speaker finishes, so the
// derived "typing" bubble can outlive a hung round forever. After this long
// without any round update, stop the typing animation and show a neutral
// status line instead. The tick keeps the flip reactive even when no new
// snapshots arrive.
const GROUP_TYPING_STALE_AFTER_MS = 150_000;
const GROUP_TYPING_STALE_TICK_MS = 15_000;

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

export type GroupParticipantIdentity = {
  name: string;
  identityLabel: string;
  fullIdentityLabel: string;
  avatarImageUrl?: string | null;
  functionLabel?: string;
  compactRole?: string;
  modelLabel?: string;
};

export type ChatGroupCenterSurfaceProps = {
  lang: "zh" | "en";
  projectBusActive: boolean;
  standardGroupRoomActive: boolean;
  groupRoomInitialLoading: boolean;
  activeGroupRoom: ChatRoomDetail | null | undefined;
  activeGroupRoomId: string;
  availableGroupParticipantCount: number;
  activeGroupParticipantById: Map<string, ChatRoomParticipant>;
  projectBusTimeline: ProjectAgentBusTimeline | null | undefined;
  projectBusEvents: ProjectAgentBusEvent[];
  projectBusDraft: string;
  projectBusInterruptTargets: boolean;
  groupTopicDraft: string;
  groupRoomActionError: string;
  groupRoundActive: boolean;
  groupRoundStopping: boolean;
  groupStopDisabled: boolean;
  expandedGroupMessageIds: string[];
  chatMentionTargets: ChatMentionTarget[];
  userDisplayName: string;
  composerLeadingControl?: ReactNode;
  projectBusRefreshing: boolean;
  projectBusRefreshError: string;
  projectBusSendPending: boolean;
  projectBusRevokePending: boolean;
  groupRoomRefreshing: boolean;
  groupRoomRefreshError: string;
  /** False while the room event stream is disconnected/reconnecting; drives the stale-typing copy. */
  groupStreamConnected?: boolean;
  /** Live speaker streaming buffers keyed by roundId then participantId; drives the streaming bubble. */
  groupSpeakerStreams?: GroupSpeakerStreamMap;
  /** Live per-speaker lifecycle projection carried by the same room stream. */
  groupSpeakerProgress?: GroupSpeakerProgressMap;
  startGroupRoundPending: boolean;
  stopGroupRoundPending: boolean;
  formatTime: (value: string) => string;
  statusLabel: (value: string) => string;
  groupParticipantIdentity: (
    participant: ChatRoomParticipant | undefined,
    fallback?: { agentId?: string; agentCode?: string; title?: string; participantId?: string; agentAvatarImageUrl?: string },
  ) => GroupParticipantIdentity;
  renderAgentAvatar: (className: string, imageUrl: string | undefined, initials: string) => ReactNode;
  avatarInitials: (agentCode?: string, name?: string, fallback?: string) => string;
  onProjectBusDraftChange: (value: string) => void;
  onProjectBusInterruptTargetsChange: (value: boolean) => void;
  onGroupTopicDraftChange: (value: string) => void;
  onRefreshProjectBus: () => void;
  onRefreshGroupRoom: () => void;
  onSendProjectBusMessage: () => void;
  onRevokeProjectBusMessage: (eventId: string) => void;
  onStartGroupRound: () => void;
  onStopGroupRound: () => void;
  onOpenMentionTarget: (target: ChatMentionTarget) => void;
  onToggleExpandedGroupMessage: (messageId: string) => void;
};

function GroupRoundsTimeline({
  rounds,
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
}: {
  rounds: ChatRoomDetail["rounds"];
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
}) {
  const hasRunningSpeaker = rounds.some((round) => {
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
      {rounds.map((round, roundIndex) => {
        const roundRunning = String(round.status ?? "").trim().toLowerCase() === "running";
        const deliveredParticipantIds = new Set(
          (round.messages ?? []).map((message) => String(message.participantId ?? "").trim()),
        );
        const pendingSpeakerIds = (round.speakerOrder ?? [])
          .map((participantId) => String(participantId ?? "").trim())
          .filter((participantId) => participantId && !deliveredParticipantIds.has(participantId));
        return (
          <section key={round.roundId} className={styles.groupRoundBlock}>
            <div className={styles.groupRoundDivider}>
              <span>
                {lang === "zh" ? `第 ${roundIndex + 1} 轮` : `Round ${roundIndex + 1}`}
                {" · "}
                {round.mode}
                {" · "}
                {round.purpose ?? purposeFallback}
                {" · "}
                {statusLabel(round.status)}
              </span>
              <time>{formatTime(round.updatedAt || round.startedAt)}</time>
            </div>
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
                          {showIdentity ? null : <time className={styles.groupBubbleMeta}>{messageTime}</time>}
                          <ChatGroupMessageBody
                            message={message}
                            identityName={speakerIdentity.name}
                            lang={lang}
                            expandedMessageIds={expandedGroupMessageIds}
                            mentionTargets={chatMentionTargets}
                            onOpenMentionTarget={onOpenMentionTarget}
                            onToggleExpanded={onToggleExpandedGroupMessage}
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
                    {hasStreamText ? (
                      <div className={styles.groupStreamCopy}>
                        <ChatGroupMessageBody
                          message={{
                            messageId: `streaming:${round.roundId}:${participantId}`,
                            participantId,
                            sessionId: speakerStream?.sessionId || "",
                            speakerCode: participant.agentCode,
                            speakerTitle: "",
                            status: "completed",
                            content: streamText,
                            summary: "",
                            timestamp: "",
                          }}
                          identityName={identity.name}
                          lang={lang}
                          expandedMessageIds={expandedGroupMessageIds}
                          mentionTargets={chatMentionTargets}
                          onOpenMentionTarget={onOpenMentionTarget}
                          onToggleExpanded={onToggleExpandedGroupMessage}
                        />
                      </div>
                    ) : progress.state === "running" && typingStale ? (
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
            {round.summary && !roundRunning ? (
              <article className={styles.groupRoundSummary}>
                <strong>{lang === "zh" ? "本轮纪要" : "Round digest"}</strong>
                <p>{round.summary}</p>
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
export function ChatGroupCenterSurface({
  lang,
  projectBusActive,
  standardGroupRoomActive,
  groupRoomInitialLoading,
  activeGroupRoom,
  activeGroupRoomId,
  availableGroupParticipantCount,
  activeGroupParticipantById,
  projectBusTimeline,
  projectBusEvents,
  projectBusDraft,
  projectBusInterruptTargets,
  groupTopicDraft,
  groupRoomActionError,
  groupRoundActive,
  groupRoundStopping,
  groupStopDisabled,
  expandedGroupMessageIds,
  chatMentionTargets,
  userDisplayName,
  composerLeadingControl,
  projectBusRefreshing,
  projectBusRefreshError,
  projectBusSendPending,
  projectBusRevokePending,
  groupRoomRefreshing,
  groupRoomRefreshError,
  groupStreamConnected,
  groupSpeakerStreams,
  groupSpeakerProgress,
  startGroupRoundPending,
  stopGroupRoundPending,
  formatTime,
  statusLabel,
  groupParticipantIdentity,
  renderAgentAvatar,
  avatarInitials,
  onProjectBusDraftChange,
  onProjectBusInterruptTargetsChange,
  onGroupTopicDraftChange,
  onRefreshProjectBus,
  onRefreshGroupRoom,
  onSendProjectBusMessage,
  onRevokeProjectBusMessage,
  onStartGroupRound,
  onStopGroupRound,
  onOpenMentionTarget,
  onToggleExpandedGroupMessage,
}: ChatGroupCenterSurfaceProps) {
  const rounds = activeGroupRoom?.rounds ?? [];
  const groupRoomTitle = activeGroupRoom?.title
    ?? (groupRoomInitialLoading
      ? (lang === "zh" ? "群聊加载中" : "Loading group")
      : groupRoomRefreshError
        ? (lang === "zh" ? "群聊加载失败" : "Group failed to load")
        : (lang === "zh" ? "暂无群聊" : "No group room"));
  const groupRoomEyebrow = activeGroupRoom
    ? `${activeGroupRoom.mode ?? "round_robin"} · ${activeGroupRoom.purpose ?? "discussion"}`
    : (lang === "zh" ? "群聊状态" : "Group status");
  const groupRoomMeta = activeGroupRoom
    ? `${availableGroupParticipantCount} ${lang === "zh" ? "位可用助手" : "available agents"} · ${statusLabel(activeGroupRoom.status ?? "ready")}`
    : groupRoomRefreshError
      ? (lang === "zh" ? "读取失败" : "Load failed")
      : (lang === "zh" ? "尚未关联群聊" : "No room linked");
  const lastRound = rounds[rounds.length - 1];
  const lastMessageKey = `${lastRound?.roundId ?? ""}:${(lastRound?.messages ?? []).length}:${rounds.length}`;
  const groupTimelineRef = useRef<HTMLDivElement | null>(null);
  const groupTimelineOpenedRoomIdRef = useRef<string | null>(null);
  const projectBusInitialLoading = projectBusRefreshing && !projectBusTimeline;

  useEffect(() => {
    if (!standardGroupRoomActive || projectBusActive || groupRoomInitialLoading) {
      if (!standardGroupRoomActive || projectBusActive) {
        groupTimelineOpenedRoomIdRef.current = null;
      }
      return;
    }
    const element = groupTimelineRef.current;
    if (!element) return;
    const firstOpen = groupTimelineOpenedRoomIdRef.current !== activeGroupRoomId;
    const nearBottom = element.scrollHeight - element.scrollTop - element.clientHeight < 180;
    if (firstOpen || nearBottom) {
      element.scrollTop = element.scrollHeight;
    }
    groupTimelineOpenedRoomIdRef.current = activeGroupRoomId;
  }, [
    activeGroupRoomId,
    groupRoomInitialLoading,
    lastMessageKey,
    projectBusActive,
    standardGroupRoomActive,
  ]);

  if (projectBusActive) {
    return (
      <div className={styles.groupConversationFrame}>
        <ChatMessageChromeHeader
          className={styles.groupConversationHeader}
          density="surface"
          titleRowClassName={styles.groupConversationTitleRow}
          eyebrow={(
            <p>
              {activeGroupRoom?.mode ?? "round_robin"}
              {" · "}
              {activeGroupRoom?.purpose ?? "discussion"}
            </p>
          )}
          title={(
            <>
              <h2>{lang === "zh" ? "助手通知流" : "Agent notice stream"}</h2>
              <VContextualHint
                content={lang === "zh"
                  ? "助手通知流会显示用户引导、助手私信和广播投递结果；它不是团队群聊。"
                  : "The Agent notice stream shows guidance, private messages, broadcasts, and delivery results. It is not a team room."}
                label={lang === "zh" ? "助手通知流说明" : "Agent notice stream details"}
                width="wide"
              />
            </>
          )}
          meta={(
            <span>
              {projectBusTimeline?.activeAgentCount ?? availableGroupParticipantCount} {lang === "zh" ? "位 active Agent" : "active agents"}
              {" · "}
              {lang === "zh" ? "全局广播与投递观察" : "broadcasts and delivery observation"}
            </span>
          )}
          trailing={(
            <VButton
              type="button"
              className={styles.groupRefreshButton}
              onClick={onRefreshProjectBus}
              isDisabled={projectBusRefreshing}
            >
              {lang === "zh" ? "刷新" : "Refresh"}
            </VButton>
          )}
        />
        {projectBusRefreshError ? (
          <div className={styles.inlineNotice} role="alert">{projectBusRefreshError}</div>
        ) : null}
        {groupRoomActionError ? (
          <div className={styles.inlineNotice} role="alert">{groupRoomActionError}</div>
        ) : null}
        <div className={styles.groupMessageTimeline} aria-live="polite">
          {projectBusInitialLoading ? (
            <ProgressiveRegionSkeleton
              variant="conversation"
              label={lang === "zh" ? "正在加载助手通知流" : "Loading Agent notice stream"}
            />
          ) : projectBusEvents.length ? (
            projectBusEvents.map((event) => {
              const revoked = isProjectAgentBusEventRevoked(event);
              const targetLabel = event.targetScope === "all"
                ? (lang === "zh" ? "全体成员" : "All agents")
                : event.targetAgentNames.length
                  ? event.targetAgentNames.join(", ")
                  : (lang === "zh" ? "仅观察" : "Observe only");
              const deliveryLabel = event.deliveries.length
                ? `${event.deliveries.length} ${lang === "zh" ? "次投递" : "deliveries"}`
                : (lang === "zh" ? "未投递" : "no delivery");
              const interruptionLabel = event.interruptions.length
                ? `${event.interruptions.filter((item) => item.status === "interrupted").length}/${event.interruptions.length} ${lang === "zh" ? "已打断" : "interrupted"}`
                : "";
              return (
                <article key={event.eventId} className={revoked ? `${styles.projectBusEvent} ${styles.projectBusEventRevoked}` : styles.projectBusEvent}>
                  <ChatMessageChromeHeader
                    className={styles.projectBusEventHeader}
                    density="surface"
                    title={(
                      <>
                        <strong>{event.createdBy === "user" ? userDisplayName : event.createdBy}</strong>
                        <span>{targetLabel}</span>
                      </>
                    )}
                    trailing={(
                      <div className={styles.projectBusEventActions}>
                        <time>{formatTime(event.createdAt)}</time>
                        {event.createdBy === "user" && !revoked ? (
                          <VButton
                            type="button"
                            onClick={() => onRevokeProjectBusMessage(event.eventId)}
                            isDisabled={projectBusRevokePending}
                          >
                            {lang === "zh" ? "撤回" : "Recall"}
                          </VButton>
                        ) : null}
                      </div>
                    )}
                  />
                  <p className={styles.projectBusEventBody}>
                    {revoked
                      ? (lang === "zh" ? "这条消息已撤回，相关 Agent 已请求停止。" : "This message was recalled. Target agents were asked to stop.")
                      : (
                        <ChatMentionedText
                          content={event.content}
                          lang={lang}
                          mentionTargets={chatMentionTargets}
                          onOpenMentionTarget={onOpenMentionTarget}
                        />
                      )}
                  </p>
                  <div className={styles.projectBusEventMeta}>
                    <span>{revoked ? (lang === "zh" ? "已撤回" : "revoked") : event.messageType}</span>
                    <span>{deliveryLabel}</span>
                    {interruptionLabel ? <span>{interruptionLabel}</span> : null}
                    {event.kernel?.taskId ? (
                      <Link className={styles.kernelTraceLink} to={kernelTaskCenterHref(event.kernel.taskId)}>
                        {lang === "zh" ? "Kernel 任务" : "Kernel Task"}
                      </Link>
                    ) : null}
                    {event.unresolvedMentions.length ? (
                      <span>{lang === "zh" ? "未识别" : "unresolved"} @{event.unresolvedMentions.join(", @")}</span>
                    ) : null}
                  </div>
                </article>
              );
            })
          ) : rounds.length ? (
            <GroupRoundsTimeline
              rounds={rounds}
              purposeFallback={activeGroupRoom?.purpose ?? "discussion"}
              userDisplayName={userDisplayName}
              lang={lang}
              formatTime={formatTime}
              statusLabel={statusLabel}
              activeGroupParticipantById={activeGroupParticipantById}
              groupParticipantIdentity={groupParticipantIdentity}
              renderAgentAvatar={renderAgentAvatar}
              avatarInitials={avatarInitials}
              expandedGroupMessageIds={expandedGroupMessageIds}
              chatMentionTargets={chatMentionTargets}
              groupStreamConnected={groupStreamConnected}
              groupSpeakerStreams={groupSpeakerStreams}
              groupSpeakerProgress={groupSpeakerProgress}
              onOpenMentionTarget={onOpenMentionTarget}
              onToggleExpandedGroupMessage={onToggleExpandedGroupMessage}
            />
          ) : (
            <div className={styles.groupEmptyState}>
              <BellRing size={28} />
              <p>{lang === "zh" ? "暂无通知。" : "No notices yet."}</p>
            </div>
          )}
        </div>
        <div className={styles.groupComposerBar}>
          <VNativeInput
            value={projectBusDraft}
            onChange={(event) => onProjectBusDraftChange(event.target.value)}
            disabled={projectBusSendPending}
            placeholder={lang === "zh" ? "输入广播；不带 @ 默认投递全体，可用 @AgentCode 指定" : "Write a broadcast; no @ sends to all, @AgentCode targets one"}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                onSendProjectBusMessage();
              }
            }}
          />
          <label className={styles.projectBusInterruptToggle}>
            <VNativeInput
              type="checkbox"
              checked={projectBusInterruptTargets}
              onChange={(event) => onProjectBusInterruptTargetsChange(event.target.checked)}
            />
            <span>{lang === "zh" ? "打断目标助手" : "Interrupt targets"}</span>
          </label>
          <VButton
            type="button"
            onClick={onSendProjectBusMessage}
            isDisabled={!projectBusDraft.trim() || projectBusSendPending}
                icon={<UsersRound size={15} />}><span>
              {projectBusSendPending
                ? (lang === "zh" ? "发送中" : "Sending")
                : (lang === "zh" ? "发送广播" : "Send")}
            </span></VButton>
        </div>
      </div>
    );
  }

  if (!standardGroupRoomActive) {
    return null;
  }

  if (groupRoomInitialLoading) {
    return (
      <div className={styles.groupConversationFrame}>
        <ProgressiveRegionSkeleton
          variant="conversation"
          label={lang === "zh" ? "正在加载群聊详情" : "Loading group details"}
        />
      </div>
    );
  }

  return (
    <div className={styles.groupConversationFrame}>
      <ChatMessageChromeHeader
        className={styles.groupConversationHeader}
        density="surface"
        eyebrow={<p>{groupRoomEyebrow}</p>}
        title={<h2>{groupRoomTitle}</h2>}
        meta={<span>{groupRoomMeta}</span>}
        trailing={(
          <VButton
            type="button"
            className={styles.groupRefreshButton}
            onClick={onRefreshGroupRoom}
            isDisabled={groupRoomRefreshing}
          >
            {lang === "zh" ? "刷新" : "Refresh"}
          </VButton>
        )}
      />
      {groupRoomRefreshError ? (
        <div className={styles.inlineNotice} role="alert">{groupRoomRefreshError}</div>
      ) : null}
      {groupRoundStopping ? (
        <div className={styles.inlineNotice} role="status" aria-live="polite">
          {lang === "zh" ? "正在停止，等待收尾。请点击刷新查看最新状态。" : "Stopping; waiting for finalization. Refresh to check the latest status."}
        </div>
      ) : null}
      <div ref={groupTimelineRef} className={styles.groupMessageTimeline} aria-live="polite">
        {rounds.length ? (
          <GroupRoundsTimeline
            rounds={rounds}
            purposeFallback={activeGroupRoom?.purpose ?? "discussion"}
            userDisplayName={userDisplayName}
            lang={lang}
            formatTime={formatTime}
            statusLabel={statusLabel}
            activeGroupParticipantById={activeGroupParticipantById}
            groupParticipantIdentity={groupParticipantIdentity}
            renderAgentAvatar={renderAgentAvatar}
            avatarInitials={avatarInitials}
            expandedGroupMessageIds={expandedGroupMessageIds}
            chatMentionTargets={chatMentionTargets}
            groupStreamConnected={groupStreamConnected}
            groupSpeakerStreams={groupSpeakerStreams}
            groupSpeakerProgress={groupSpeakerProgress}
            onOpenMentionTarget={onOpenMentionTarget}
            onToggleExpandedGroupMessage={onToggleExpandedGroupMessage}
          />
        ) : (
          <div className={styles.groupEmptyState}>
            <UsersRound size={28} />
            <p>
              {activeGroupRoom
                ? (lang === "zh" ? "群聊已创建，输入议题后开始第一轮讨论。" : "The group is ready. Enter a topic to start the first round.")
                : groupRoomRefreshError
                  ? (lang === "zh" ? "群聊详情读取失败，请点击刷新重试。" : "The group details could not be loaded. Refresh to retry.")
                  : (lang === "zh" ? "当前没有可用群聊，请先创建或关联群聊。" : "No group room is available. Create or link a room first.")}
            </p>
          </div>
        )}
      </div>
      <div className={styles.groupComposerBar}>
        {composerLeadingControl}
        <VNativeInput
          value={groupTopicDraft}
          onChange={(event) => onGroupTopicDraftChange(event.target.value)}
          disabled={startGroupRoundPending || groupRoundStopping}
          placeholder={lang === "zh" ? "输入下一轮群聊议题" : "Topic for the next group round"}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              onStartGroupRound();
            }
          }}
        />
        <VButton
          type="button"
          onClick={onStartGroupRound}
          isDisabled={
            !groupTopicDraft.trim()
            || startGroupRoundPending
            || groupRoundActive
            || groupRoundStopping
            || !activeGroupRoom
          }
                icon={<UsersRound size={15} />}><span>
            {groupRoundStopping
              ? (lang === "zh" ? "等待收尾" : "Waiting to finish")
              : startGroupRoundPending || groupRoundActive
                ? (groupRoundActive ? (lang === "zh" ? "讨论中" : "Running") : (lang === "zh" ? "启动中" : "Starting"))
              : (lang === "zh" ? "启动一轮" : "Run round")}
          </span></VButton>
        {groupRoundActive && !groupRoundStopping ? (
          <VButton
            type="button"
            className={styles.groupStopButton}
            onClick={onStopGroupRound}
            isDisabled={groupStopDisabled}
            title={lang === "zh" ? "停止当前群聊轮次" : "Stop current group round"}
                icon={<Square size={15} />}><span>
              {stopGroupRoundPending
                ? (lang === "zh" ? "停止中" : "Stopping")
                : (lang === "zh" ? "停止" : "Stop")}
            </span></VButton>
        ) : null}
      </div>
    </div>
  );
}
