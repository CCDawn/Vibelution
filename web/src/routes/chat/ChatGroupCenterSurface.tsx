import { ArrowLeft, ArrowUp, Square, UsersRound } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import type {
  ChatRoomDetail,
  ChatRoomParticipant,
  ProjectAgentBusEvent,
  ProjectAgentBusTimeline,
} from "../../api/types";
import { VButton, VConfirmDialog, VDialog, VTextarea } from "../../components/vui";
import type { ChatMentionTarget } from "../chatMentionTokens";
import { ProgressiveRegionSkeleton } from "../shared/ProgressiveRegionSkeleton";
import styles from "./ChatGroupCenterSurface.styles";
import { GroupRoundsTimeline } from "./ChatGroupRoundsTimeline";
import { ChatProjectBusSurface } from "./ChatProjectBusSurface";
import { ChatGroupArtifactDialog } from "./ChatGroupArtifactDialog";
import { ChatMessageChromeHeader } from "./ChatMessageChromeHeader";
import { chatRoomModeLabel, chatRoomPurposeLabel, isAvailableGroupParticipant } from "./chatRoutePresentation";
import type { GroupSpeakerProgressMap, GroupSpeakerStreamMap } from "./useGroupRoomStream";
import type { GroupRoomTimelineProjection } from "./useGroupRoomTimeline";
import { roundsToTimelineItems } from "./useGroupRoomTimeline";

// The backend only publishes a full snapshot when a speaker finishes, so the
// derived "typing" bubble can outlive a hung round forever. After this long
// without any round update, stop the typing animation and show a neutral
// status line instead. The tick keeps the flip reactive even when no new
// snapshots arrive.
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
  visibleGroupParticipants?: readonly ChatRoomParticipant[];
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
  /**
   * Timeline projection (message-list authority). When omitted the surface
   * falls back to rendering the room detail rounds directly — the legacy
   * hand-test/preview path and the pre-timeline behavior contract.
   */
  groupTimeline?: GroupRoomTimelineProjection;
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
  /** Ordinary-chat parity: workspace file links open in the right rail. */
  workspaceRoot?: string;
  onOpenRailFile?: (path: string) => void;
  onOpenGroupTeam?: () => void;
  onManageGroupRoom?: () => void;
  artifactTeamId?: string;
};

export function ChatGroupCenterSurface({
  lang,
  projectBusActive,
  standardGroupRoomActive,
  groupRoomInitialLoading,
  activeGroupRoom,
  activeGroupRoomId,
  availableGroupParticipantCount,
  visibleGroupParticipants,
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
  groupTimeline,
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
  workspaceRoot,
  onOpenRailFile,
  onOpenGroupTeam,
  onManageGroupRoom,
  artifactTeamId,
}: ChatGroupCenterSurfaceProps) {
  const [artifactSelection, setArtifactSelection] = useState<{
    roomId: string; teamId: string; taskIds: string[];
  } | null>(null);
  const artifactTaskIds = artifactSelection?.roomId === activeGroupRoomId
    && artifactSelection.teamId === artifactTeamId ? artifactSelection.taskIds : [];
  const artifactTriggerRef = useRef<HTMLElement | null>(null);
  useEffect(() => setArtifactSelection(null), [activeGroupRoomId, artifactTeamId]);
  const [membersOpen, setMembersOpen] = useState(false);
  const [confirmStopOpen, setConfirmStopOpen] = useState(false);
  const membersTriggerRef = useRef<HTMLElement | null>(null);
  const membersManagementHandoffRef = useRef(false);
  const stopTriggerRef = useRef<HTMLElement | null>(null);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);
  useEffect(() => { setMembersOpen(false); setConfirmStopOpen(false); }, [activeGroupRoomId]);
  // Single render path: the timeline projection when present (message-list
  // authority, member-change system rows, cursor paging), otherwise the room
  // detail rounds rendered through the same view model (legacy hand-test path).
  const timelineItems = groupTimeline
    ? groupTimeline.items
    : roundsToTimelineItems(activeGroupRoom?.rounds);
  const rounds = timelineItems.flatMap((item) => (item.kind === "round" ? [item.round] : []));
  const groupRoomTitle = activeGroupRoom?.title
    ?? (groupRoomInitialLoading
      ? (lang === "zh" ? "群聊加载中" : "Loading group")
      : groupRoomRefreshError
        ? (lang === "zh" ? "群聊加载失败" : "Group failed to load")
        : (lang === "zh" ? "暂无群聊" : "No group room"));
  const groupRoomEyebrow = activeGroupRoom
    ? `${chatRoomModeLabel({ id: activeGroupRoom.mode ?? "round_robin", label: "", status: "active" }, lang)} · ${chatRoomPurposeLabel({ id: activeGroupRoom.purpose ?? "discussion", label: "" }, lang)}`
    : (lang === "zh" ? "群聊状态" : "Group status");
  const groupRoomMeta = activeGroupRoom
    ? (groupRoundStopping ? (lang === "zh" ? "停止中" : "Stopping") : groupRoundActive ? (lang === "zh" ? "讨论中" : "Running") : statusLabel(activeGroupRoom.status ?? "ready"))
    : groupRoomRefreshError
      ? (lang === "zh" ? "读取失败" : "Load failed")
      : (lang === "zh" ? "尚未关联群聊" : "No room linked");
  const lastRound = rounds[rounds.length - 1];
  const latestInvalidCount = (lastRound?.messages ?? []).filter((message) => message.messagePayload?.kind === "challenge_meeting_message" && message.messagePayload.audit?.parseStatus === "invalid").length;
  const lastMessageKey = `${lastRound?.roundId ?? ""}:${(lastRound?.messages ?? []).length}:${rounds.length}`;
  const streamedLength = Object.values(groupSpeakerStreams ?? {}).reduce((sum, speakers) => sum + Object.values(speakers).reduce((length, speaker) => length + speaker.content.length, 0), 0);
  const groupTimelineRef = useRef<HTMLDivElement | null>(null);
  const [groupBackToBottomVisible, setGroupBackToBottomVisible] = useState(false);
  const groupTimelineFollowingRef = useRef(true);
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
    const latestRound = element.querySelectorAll<HTMLElement>("[data-group-round-id]").item(rounds.length - 1);
    if (firstOpen && lastRound?.status !== "running" && latestRound) {
      element.scrollTop += latestRound.getBoundingClientRect().top - element.getBoundingClientRect().top;
      groupTimelineFollowingRef.current = element.scrollHeight - element.scrollTop - element.clientHeight < 180;
    } else if (firstOpen || groupTimelineFollowingRef.current) {
      element.scrollTop = element.scrollHeight;
      groupTimelineFollowingRef.current = true;
    }
    groupTimelineOpenedRoomIdRef.current = activeGroupRoomId;
  }, [
    activeGroupRoomId,
    groupRoomInitialLoading,
    lastMessageKey,
    streamedLength,
    lastRound?.status,
    rounds.length,
    projectBusActive,
    standardGroupRoomActive,
  ]);

  if (projectBusActive) {
    return (
      <ChatProjectBusSurface
        lang={lang}
        projectBusTimeline={projectBusTimeline}
        projectBusEvents={projectBusEvents}
        projectBusDraft={projectBusDraft}
        projectBusInterruptTargets={projectBusInterruptTargets}
        projectBusRefreshing={projectBusRefreshing}
        projectBusRefreshError={projectBusRefreshError}
        projectBusSendPending={projectBusSendPending}
        projectBusRevokePending={projectBusRevokePending}
        projectBusInitialLoading={projectBusInitialLoading}
        groupRoomActionError={groupRoomActionError}
        userDisplayName={userDisplayName}
        chatMentionTargets={chatMentionTargets}
        composerLeadingControl={composerLeadingControl}
        formatTime={formatTime}
        onProjectBusDraftChange={onProjectBusDraftChange}
        onProjectBusInterruptTargetsChange={onProjectBusInterruptTargetsChange}
        onRefreshProjectBus={onRefreshProjectBus}
        onSendProjectBusMessage={onSendProjectBusMessage}
        onRevokeProjectBusMessage={onRevokeProjectBusMessage}
        onOpenMentionTarget={onOpenMentionTarget}
      />
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
        eyebrow={<p>{lang === "zh" ? "团队讨论" : "Team discussion"}</p>}
        title={<h2>{groupRoomTitle}</h2>}
        meta={<span>{latestInvalidCount > 0 && lastRound?.status !== "running"
          ? (lang === "zh" ? `最近一轮有 ${latestInvalidCount} 条科研发言解析失败 · 结果待处理` : `Latest round: ${latestInvalidCount} research messages failed parsing · results need attention`)
          : groupRoomMeta}</span>}
        trailing={(
          <div className={styles.groupHeaderActions}>
          {onOpenGroupTeam ? <VButton variant="ghost" isIconOnly aria-label={lang === "zh" ? "返回团队工作台" : "Back to team"} icon={<ArrowLeft size={17} />} onClick={onOpenGroupTeam} /> : null}
          <VButton variant="ghost" icon={<UsersRound size={16} />} isDisabled={!activeGroupRoom}
            onClick={(event) => { membersManagementHandoffRef.current = false; membersTriggerRef.current = event.currentTarget; setMembersOpen(true); }}>
            {lang === "zh" ? "成员" : "Members"}
          </VButton>
          <VButton
            type="button"
            className={styles.groupRefreshButton}
            onClick={onRefreshGroupRoom}
            isDisabled={groupRoomRefreshing}
          >
            {lang === "zh" ? "刷新" : "Refresh"}
          </VButton>
          </div>
        )}
      />
      <div className={styles.groupTimelineHost}>
      <div ref={groupTimelineRef} className={styles.groupMessageTimeline} role="log" aria-label={lang === "zh" ? "团队发言" : "Team messages"} aria-live="polite" aria-relevant="additions text"
        onScroll={(event) => { const element = event.currentTarget; const atBottom = element.scrollHeight - element.scrollTop - element.clientHeight < 180; groupTimelineFollowingRef.current = atBottom; setGroupBackToBottomVisible((current) => current === !atBottom ? current : !atBottom); }}>
        {groupRoomRefreshError ? <div className={styles.inlineNotice} role="alert">{groupRoomRefreshError}</div> : null}
        {groupRoundStopping ? <p className={styles.groupTypingStaleNote} role="status">{lang === "zh" ? "正在停止，已有发言会保留。" : "Stopping. Existing messages will be kept."}</p> : null}
        {timelineItems.length ? (
          <>
            <GroupRoundsTimeline
              items={timelineItems}
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
              workspaceRoot={workspaceRoot}
              onOpenRailFile={onOpenRailFile}
              onOpenArtifacts={artifactTeamId ? (taskIds, trigger) => {
                artifactTriggerRef.current = trigger;
                setArtifactSelection({ roomId: activeGroupRoomId, teamId: artifactTeamId, taskIds });
              } : undefined}
            />
            {groupTimeline?.hasMore ? (
              <div className={styles.groupRoundActions}>
                <VButton
                  type="button"
                  variant="secondary"
                  onClick={groupTimeline.loadMore}
                  isDisabled={groupTimeline.loadingMore}
                >
                  {groupTimeline.loadingMore
                    ? (lang === "zh" ? "加载中…" : "Loading…")
                    : (lang === "zh" ? "加载更多记录" : "Load more records")}
                </VButton>
              </div>
            ) : null}
          </>
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
      {groupBackToBottomVisible ? (
        <VButton
          type="button"
          isIconOnly
          className={styles.groupBackToBottom}
          aria-label={lang === "zh" ? "回到底部" : "Back to bottom"}
          title={lang === "zh" ? "回到底部" : "Back to bottom"}
          icon={<ArrowUp size={16} className="rotate-180" />}
          onClick={() => {
            const element = groupTimelineRef.current;
            if (element) {
              element.scrollTo({ top: element.scrollHeight, behavior: "smooth" });
            }
          }}
        />
      ) : null}
      </div>
      <div className={styles.groupTopicComposer}>
        {groupRoomActionError ? <div className={styles.inlineNotice} role="alert">{groupRoomActionError}</div> : null}
        <div className={styles.groupTopicComposerField}>
        <VTextarea
          ref={composerRef}
          value={groupTopicDraft}
          onChange={(event) => onGroupTopicDraftChange(event.target.value)}
          disabled={startGroupRoundPending || groupRoundStopping}
          rows={2}
          className={styles.groupTopicInput}
          aria-label={lang === "zh" ? "下一轮议题" : "Next round topic"}
          placeholder={lang === "zh" ? "输入下一轮群聊议题" : "Topic for the next group round"}
          onKeyDown={(event) => {
            if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && !event.nativeEvent.isComposing
              && groupTopicDraft.trim() && !groupRoundActive && !groupRoundStopping && !startGroupRoundPending && activeGroupRoom) {
              event.preventDefault();
              onStartGroupRound();
            }
          }}
        />
        <div className={styles.groupTopicComposerActions}>
        <div>{composerLeadingControl}</div>
        {groupRoundActive && !groupRoundStopping ? (
          <VButton type="button" variant="secondary" className={styles.groupStopButton}
            onClick={(event) => { stopTriggerRef.current = event.currentTarget; setConfirmStopOpen(true); }}
            isDisabled={groupStopDisabled} icon={<Square size={14} />}>
            {stopGroupRoundPending ? (lang === "zh" ? "停止中" : "Stopping") : (lang === "zh" ? "停止本轮" : "Stop round")}
          </VButton>
        ) : <VButton
          type="button"
          onClick={onStartGroupRound}
          isDisabled={
            !groupTopicDraft.trim()
            || startGroupRoundPending
            || groupRoundActive
            || groupRoundStopping
            || !activeGroupRoom
          }
          icon={<ArrowUp size={15} />}><span>
            {groupRoundStopping
              ? (lang === "zh" ? "等待收尾" : "Waiting to finish")
              : startGroupRoundPending || groupRoundActive
                ? (groupRoundActive ? (lang === "zh" ? "讨论中" : "Running") : (lang === "zh" ? "启动中" : "Starting"))
              : (lang === "zh" ? "启动一轮" : "Run round")}
          </span></VButton>}
        </div>
        </div>
        <div className={styles.groupComposerFootnote}><span>{lang === "zh" ? "发送给团队" : "Send to team"}</span><span>{lang === "zh" ? "Ctrl + Enter 启动一轮" : "Ctrl + Enter to start"}</span></div>
      </div>
      <VDialog open={membersOpen} onOpenChange={setMembersOpen} title={lang === "zh" ? "团队成员" : "Team members"}
        contentClassName="!left-auto !right-0 !top-0 !h-[100dvh] !max-h-[100dvh] !w-[min(100%,380px)] !transform-none !translate-x-0 !translate-y-0 !rounded-none"
        onCloseAutoFocus={(event) => { event.preventDefault(); if (!membersManagementHandoffRef.current) membersTriggerRef.current?.focus({ preventScroll: true }); }}>
        <p className={styles.groupMemberMeta}>{availableGroupParticipantCount} {lang === "zh" ? "位成员" : "members"} · {groupRoomEyebrow}</p>
        <div className={styles.groupMembers}>
          {(visibleGroupParticipants ?? [...activeGroupParticipantById.values()].filter(isAvailableGroupParticipant)).map((participant) => {
            const identity = groupParticipantIdentity(participant);
            return <div key={participant.participantId} className={styles.groupMemberRow}>
              {renderAgentAvatar(styles.groupBubbleAvatar, identity.avatarImageUrl || undefined, avatarInitials(participant.agentCode, identity.name, "AI"))}
              <div className={styles.groupMemberCopy}><strong className={styles.groupMemberName}>{identity.name}</strong><span className={styles.groupMemberMeta}>{identity.functionLabel || identity.compactRole || identity.modelLabel}</span></div>
              <span className={styles.groupMemberMeta}>{statusLabel(participant.status || "ready")}</span>
            </div>;
          })}
        </div>
        {onManageGroupRoom ? <VButton variant="secondary" className={styles.groupManageAction} onClick={() => { membersManagementHandoffRef.current = true; setMembersOpen(false); onManageGroupRoom(); }}>{lang === "zh" ? "管理群聊" : "Manage group"}</VButton> : null}
      </VDialog>
      <VConfirmDialog open={confirmStopOpen} onOpenChange={setConfirmStopOpen}
        title={lang === "zh" ? "停止本轮讨论？" : "Stop this round?"}
        description={lang === "zh" ? "已有发言与产出会保留。" : "Existing messages and outputs will be kept."}
        confirmLabel={lang === "zh" ? "停止本轮" : "Stop round"} cancelLabel={lang === "zh" ? "继续讨论" : "Keep discussing"}
        confirmDisabled={groupStopDisabled || !groupRoundActive || groupRoundStopping}
        onCloseAutoFocus={(event) => { event.preventDefault(); (stopTriggerRef.current?.isConnected ? stopTriggerRef.current : composerRef.current)?.focus({ preventScroll: true }); }}
        onConfirm={() => { setConfirmStopOpen(false); if (!groupStopDisabled && groupRoundActive && !groupRoundStopping) onStopGroupRound(); }} />
      {artifactTeamId && artifactTaskIds.length > 0 ? (
        <ChatGroupArtifactDialog teamId={artifactTeamId} taskIds={artifactTaskIds} lang={lang}
          open onOpenChange={(open) => { if (!open) setArtifactSelection(null); }}
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            artifactTriggerRef.current?.focus({ preventScroll: true });
          }} />
      ) : null}
    </div>
  );
}
