import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { ArrowUpRight, GitBranch, MessageSquare, Play, Square } from "lucide-react";

import { queryKeys } from "../../api/queryKeys";
import type { AgentInstance, ChatRoomDetail, ChatRoomMessage, ChatRoomRound, Team } from "../../api/types";
import {
  VButton,
  VConfirmDialog,
  VRouteLinkButton,
  VStateSurface,
  VStatusChip,
  VTextarea,
  VUI_WORKBENCH_TOOLBAR_CLASS,
} from "../../components/vui";
import { ChatGroupMessageBody } from "../chat/ChatGroupMessagePresentation";
import { useGroupRoomTimeline } from "../chat/useGroupRoomTimeline";
import { DevTeamTaskBoard, speakingTeamMemberIdFromRoom } from "./DevTeamTaskBoard";
import { formatTime } from "./source-collection/presentationModel";
import { teamChatRoomRoute } from "./researchStageAgentPresentation";
import { teamWorkspaceRoute } from "./researchWorkspaceModel";
import styles from "./TeamHomeSurface.styles";
import { TeamWorkspaceFrame, type TeamWorkspaceFrameProps } from "./TeamWorkspaceFrame";
import { WORKBENCH_LAYOUT_IDS } from "../../components/layout/workbenchLayoutIds";
import { TeamNativeConversation } from "./TeamNativeConversation";
import { teamMemberDisplay, teamMemberSessionId } from "./TeamConversationRail";

export type StartTeamRoundPayload = {
  roomId: string;
  teamId: string;
  topic: string;
  mode: string;
  purpose: string;
};

export type TeamHomeSurfaceProps = {
  lang: "zh" | "en";
  selectedTeam: Team | null;
  linkedChatRoomId: string;
  linkedRoomDetail: ChatRoomDetail | null;
  linkedRoomBusy: boolean;
  linkedChatRoomPending: boolean;
  linkedChatRoomError: Error | null;
  latestTeamRound: ChatRoomRound | null;
  teamTaskTopic: string;
  onTeamTaskTopicChange: (value: string) => void;
  canStartTeamRound: boolean;
  startRoundPending: boolean;
  startRoundError: Error | null;
  onStartTeamRound: (payload: StartTeamRoundPayload) => void;
  stopRoundPending: boolean;
  stopRoundError: Error | null;
  onStopTeamRound: (payload: { roomId: string; teamId: string }) => void;
  activeTeamMemberCount: number;
  teamSyncPending: boolean;
  onSyncRoom: () => void;
  onOpenOrganization: () => void;
  conversationRequested?: boolean;
  agentsById?: ReadonlyMap<string, Partial<AgentInstance>>;
  workspace?: { navigation: ReactNode; teamSwitcher: ReactNode; toolbar: ReactNode; canvas: ReactNode; inspector: ReactNode; resize: TeamWorkspaceFrameProps["resize"] };
};

const roundStateCopy: Record<string, { zh: string; en: string; tone: "neutral" | "accent" | "success" | "warning" | "danger" }> = {
  running: { zh: "进行中", en: "Running", tone: "accent" },
  stopping: { zh: "停止中", en: "Stopping", tone: "warning" },
  completed: { zh: "已完成", en: "Completed", tone: "success" },
  partial: { zh: "部分完成", en: "Partially complete", tone: "warning" },
  failed: { zh: "失败", en: "Failed", tone: "danger" },
  blocked: { zh: "受阻", en: "Blocked", tone: "warning" },
  stopped: { zh: "已停止", en: "Stopped", tone: "neutral" },
  queued: { zh: "等待开始", en: "Queued", tone: "neutral" },
};

function RoundStatus({ status, lang }: { status: string; lang: "zh" | "en" }) {
  const normalizedStatus = String(status || "").toLowerCase();
  const state = roundStateCopy[normalizedStatus] ?? {
    zh: "状态同步中",
    en: "Syncing status",
    tone: "neutral",
  };
  return (
    <VStatusChip className={styles.status} tone={state.tone}>{lang === "zh" ? state.zh : state.en}</VStatusChip>
  );
}

function isDeliverySummary(summary: string) {
  return /^本轮群聊完成：\d+\/\d+ 位参与者成功发言/.test(summary.trim())
    || /^Chat room round finished: \d+\/\d+ participants responded successfully;/.test(summary.trim());
}

function messageLabel(
  message: ChatRoomMessage,
  selectedTeam: Team | null,
  linkedRoomDetail: ChatRoomDetail | null,
  lang: "zh" | "en",
) {
  const speakerParticipantId = String(
    (message as ChatRoomMessage & { speakerParticipantId?: string }).speakerParticipantId
      || message.participantId
      || "",
  ).trim();
  const participant = linkedRoomDetail?.participants?.find(
    (item) => String(item.participantId || "").trim() === speakerParticipantId,
  );
  const agentId = String(participant?.agentId || message.agentId || "").trim();
  const teamMember = selectedTeam?.members?.find((member) => member.agentId === agentId);
  const agentName = String(teamMember?.agentName || "").trim();
  if (agentName) return agentName;

  const title = String(message.speakerTitle || "").trim();
  if (!title || title.toLowerCase() === "user") return lang === "zh" ? "你" : "You";
  return title;
}

function RoundMessages({
  round,
  lang,
  roomLink,
  selectedTeam,
  linkedRoomDetail,
  waitingForTimeline,
}: {
  round: ChatRoomRound | null;
  lang: "zh" | "en";
  roomLink?: string;
  selectedTeam: Team | null;
  linkedRoomDetail: ChatRoomDetail | null;
  waitingForTimeline: boolean;
}) {
  const [expandedMessageIds, setExpandedMessageIds] = useState<string[]>([]);
  const messages = (round?.messages ?? []).slice(-4);

  if (!round) {
    return (
      <p role={waitingForTimeline ? "status" : undefined} className={styles.emptyMessages}>
        {waitingForTimeline
          ? (lang === "zh" ? "正在同步本轮发言…" : "Syncing messages for this round…")
          : (lang === "zh" ? "还没有团队任务记录。" : "No team task history yet.")}
      </p>
    );
  }
  if (!messages.length) {
    return <p className={styles.emptyMessages}>{lang === "zh" ? "本轮暂时没有可展示的发言。" : "No visible messages in this round yet."}</p>;
  }

  return (
    <>
      <ol className={styles.messageList}>
        {messages.map((message) => (
          <li key={message.messageId} className={styles.messageRow}>
            <div className={styles.messageHeader}>
              <strong className={styles.speaker}>{messageLabel(message, selectedTeam, linkedRoomDetail, lang)}</strong>
              <time className={styles.messageTime}>{formatTime(message.timestamp, lang)}</time>
            </div>
            <div className={styles.messageBody}>
              <ChatGroupMessageBody
                message={message}
                identityName={messageLabel(message, selectedTeam, linkedRoomDetail, lang)}
                lang={lang}
                expandedMessageIds={expandedMessageIds}
                mentionTargets={[]}
                onOpenMentionTarget={() => undefined}
                onToggleExpanded={(messageId) => setExpandedMessageIds((current) => (
                  current.includes(messageId)
                    ? current.filter((id) => id !== messageId)
                    : [...current, messageId]
                ))}
              />
            </div>
          </li>
        ))}
      </ol>
      {round.messagesTruncated && roomLink ? (
        <VRouteLinkButton to={roomLink} variant="ghost" className={styles.earlierLink} trailingIcon={<ArrowUpRight size={14} aria-hidden="true" />}>
          {lang === "zh" ? "查看更早发言" : "View earlier messages"}
        </VRouteLinkButton>
      ) : null}
    </>
  );
}

export function TeamHomeSurface(props: TeamHomeSurfaceProps) {
  const {
    lang,
    selectedTeam,
    linkedChatRoomId,
    linkedRoomDetail,
    linkedRoomBusy,
    linkedChatRoomPending,
    linkedChatRoomError,
    latestTeamRound,
    teamTaskTopic,
    onTeamTaskTopicChange,
    canStartTeamRound,
    startRoundPending,
    startRoundError,
    onStartTeamRound,
    stopRoundPending,
    stopRoundError,
    onStopTeamRound,
    activeTeamMemberCount,
    teamSyncPending,
    onSyncRoom,
    onOpenOrganization,
  } = props;
  const teamId = selectedTeam?.teamId || "";
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const [confirmStopOpen, setConfirmStopOpen] = useState(false);
  const [homeView, setHomeView] = useState<"canvas" | "conversation">(props.workspace ? "canvas" : "conversation");
  const nativeConversationOpen = Boolean(props.workspace && props.conversationRequested
    && searchParams.get("teamConversationTeamId") === teamId
    && ["group", "member"].includes(searchParams.get("teamConversation") || ""));
  const memberConversation = nativeConversationOpen && searchParams.get("teamConversation") === "member";
  const selectedMember = memberConversation ? selectedTeam?.members.find((member) => member.memberId === searchParams.get("teamMember")) : undefined;
  const selectedMemberSessionId = selectedMember ? teamMemberSessionId(selectedMember, linkedRoomDetail) : "";
  const selectedMemberDisplay = selectedMember ? teamMemberDisplay(selectedMember, props.agentsById, lang) : null;
  const nativeSelectionReady = memberConversation
    ? Boolean(selectedMemberSessionId && !searchParams.get("room") && searchParams.get("session") === selectedMemberSessionId && selectedMember?.agentStatus !== "stale")
    : Boolean(linkedChatRoomId && !searchParams.get("session") && searchParams.get("room") === linkedChatRoomId);
  function openHomeView(nextView: "canvas" | "conversation") {
    setHomeView(nextView);
    const next = new URLSearchParams(searchParams);
    next.delete("session"); next.delete("room"); next.delete("teamMember");
    if (nextView === "conversation") {
      next.set("teamConversationTeamId", teamId); next.set("teamConversation", "group");
      if (linkedChatRoomId) next.set("room", linkedChatRoomId);
    } else {
      next.set("teamConversationTeamId", teamId); next.set("teamConversation", "canvas");
      next.delete("returnTo"); next.delete("returnLabel");
    }
    setSearchParams(next);
  }
  useEffect(() => {
    if (!nativeConversationOpen || memberConversation || !linkedChatRoomId || searchParams.get("room") === linkedChatRoomId) return;
    const next = new URLSearchParams(searchParams); next.set("room", linkedChatRoomId); next.delete("session");
    setSearchParams(next, { replace: true });
  }, [linkedChatRoomId, memberConversation, nativeConversationOpen, searchParams, setSearchParams]);
  const stopTriggerRef = useRef<HTMLButtonElement | null>(null);
  const lastRoomRevisionRef = useRef<{ roomId: string; revision: string } | null>(null);
  const groupTimeline = useGroupRoomTimeline({
    roomId: linkedChatRoomId,
    enabled: Boolean(linkedChatRoomId),
    detail: linkedRoomDetail,
  });
  const timelineLatestRound = [...groupTimeline.items].reverse().find((item) => item.kind === "round");
  const currentTeamRound = latestTeamRound ?? (
    groupTimeline.legacyFromDetail && timelineLatestRound?.kind === "round"
      ? timelineLatestRound.round
      : null
  );
  const timelineRoundId = timelineLatestRound?.kind === "round"
    ? String(timelineLatestRound.round.roundId || "").trim()
    : "";
  const currentRoundId = String(currentTeamRound?.roundId || "").trim();
  const transcriptRound = groupTimeline.legacyFromDetail
    ? currentTeamRound
    : currentRoundId && timelineRoundId === currentRoundId && timelineLatestRound?.kind === "round"
      ? timelineLatestRound.round
      : null;

  useEffect(() => {
    if (!linkedChatRoomId) {
      lastRoomRevisionRef.current = null;
      return;
    }
    if (!linkedRoomDetail) return;

    const revision = `${linkedRoomDetail.updatedAt || ""}|${latestTeamRound?.updatedAt || ""}`;
    const previous = lastRoomRevisionRef.current;
    lastRoomRevisionRef.current = { roomId: linkedChatRoomId, revision };
    if (previous?.roomId === linkedChatRoomId && previous.revision !== revision) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.chatRoomTimeline(linkedChatRoomId) });
    }
  }, [latestTeamRound?.updatedAt, linkedChatRoomId, linkedRoomDetail, queryClient]);

  const roomLink = linkedChatRoomId && teamId
    ? teamChatRoomRoute(linkedChatRoomId, teamWorkspaceRoute(teamId), lang === "zh" ? "返回团队页面" : "Back to team")
    : undefined;
  const currentStatus = currentTeamRound?.status || (linkedRoomBusy ? "running" : "queued");
  const currentTitle = currentTeamRound?.topic?.trim() || (lang === "zh" ? "还没有团队任务" : "No team task yet");
  const currentSummary = transcriptRound?.summary?.trim();
  const deliveryOnlySummary = currentSummary ? isDeliverySummary(currentSummary) : false;

  const startRound = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedTeam || !linkedChatRoomId || !teamTaskTopic.trim() || !canStartTeamRound) return;
    onStartTeamRound({
      roomId: linkedChatRoomId,
      teamId: selectedTeam.teamId,
      topic: teamTaskTopic.trim(),
      mode: linkedRoomDetail?.mode || selectedTeam.linkedChatRoom?.mode || "round_robin",
      purpose: linkedRoomDetail?.purpose || selectedTeam.linkedChatRoom?.purpose || "discussion",
    });
  };

  const stopRound = () => {
    if (!selectedTeam || !linkedChatRoomId || stopRoundPending || linkedRoomDetail?.status === "stopping") return;
    setConfirmStopOpen(true);
  };

  const confirmStopRound = () => {
    if (!selectedTeam || !linkedChatRoomId || stopRoundPending || linkedRoomDetail?.status === "stopping") return;
    setConfirmStopOpen(false);
    onStopTeamRound({ roomId: linkedChatRoomId, teamId: selectedTeam.teamId });
  };

  const conversation = <div className={styles.conversation}>
    <header className={`${VUI_WORKBENCH_TOOLBAR_CLASS} ${styles.header}`}><div className={styles.headerCopy}>
          <p className={styles.eyebrow}>{lang === "zh" ? "当前任务" : "Current task"}</p>
          <h2 className={styles.title}>{currentTitle}</h2>
          <div className={styles.statusRow}>
            <RoundStatus status={currentStatus} lang={lang} />
            {currentTeamRound?.updatedAt || currentTeamRound?.startedAt ? (
              <time className={styles.updatedTime}>{lang === "zh" ? "更新于" : "Updated"} {formatTime(currentTeamRound.updatedAt || currentTeamRound.startedAt, lang)}</time>
            ) : null}
          </div>
        </div></header>
    <div className={styles.transcript}>
          {selectedTeam?.teamTemplateId === "dev-team" && selectedTeam.teamId ? (
            <section className={styles.taskBoard} aria-label={lang === "zh" ? "共享任务板" : "Shared task board"}>
              <DevTeamTaskBoard
                lang={lang}
                teamId={selectedTeam.teamId}
                members={selectedTeam.members ?? []}
                speakingMemberId={speakingTeamMemberIdFromRoom(selectedTeam.members ?? [], linkedRoomDetail)}
              />
            </section>
          ) : null}
          {currentSummary ? (
            <section aria-labelledby="team-home-round-result" className={styles.result}>
              {deliveryOnlySummary ? (
                <details className={styles.deliveryDetails}>
                  <summary className={styles.deliverySummary}>{lang === "zh" ? "轮次结果" : "Round result"}</summary>
                  <p className={styles.deliveryBody}>{currentSummary}</p>
                </details>
              ) : (
                <>
                  <h3 id="team-home-round-result" className={styles.resultTitle}>{lang === "zh" ? "本轮结论" : "Round conclusion"}</h3>
                  <p className={styles.conclusionBody}>{currentSummary}</p>
                </>
              )}
            </section>
          ) : null}

          <section aria-labelledby="team-home-recent-messages" className={currentSummary ? styles.messagesAfterResult : undefined}>
            <div className={styles.sectionHeader}>
              <MessageSquare size={15} className={styles.sectionIcon} aria-hidden="true" />
              <h3 id="team-home-recent-messages" className={styles.sectionTitle}>{lang === "zh" ? "近期发言" : "Recent messages"}</h3>
            </div>

            {linkedChatRoomPending && linkedChatRoomId ? (
              <VStateSurface tone="loading" density="compact" title={lang === "zh" ? "正在读取群聊" : "Loading room"} skeletonLines={2} className={styles.spaceAbove} />
            ) : linkedChatRoomError ? (
              <VStateSurface tone="error" density="compact" title={lang === "zh" ? "群聊读取失败" : "Could not load room"} className={styles.spaceAbove}>
                {lang === "zh" ? "请稍后刷新团队。" : "Refresh the team and try again."}
              </VStateSurface>
            ) : (
              <RoundMessages
                round={transcriptRound}
                lang={lang}
                roomLink={roomLink}
                selectedTeam={selectedTeam}
                linkedRoomDetail={linkedRoomDetail}
                waitingForTimeline={Boolean(currentTeamRound && !transcriptRound)}
              />
            )}
          </section>
        </div>
  </div>;
  const roundActions = <aside className={styles.actionRail}>
          <section aria-labelledby="team-home-round-action">
            <h3 id="team-home-round-action" className={styles.sectionTitle}>
              {linkedRoomBusy ? (lang === "zh" ? "本轮正在运行" : "Round in progress") : (lang === "zh" ? "开始下一轮" : "Start next round")}
            </h3>

            {!linkedChatRoomId ? (
              <div className={styles.spaceAbove}>
                <p className={styles.actionCopy}>{lang === "zh" ? "还没有关联群聊" : "No linked room"}</p>
                <VButton
                  className={styles.spacedAction}
                  variant="secondary"
                  isPending={teamSyncPending}
                  isDisabled={!selectedTeam || activeTeamMemberCount === 0 || teamSyncPending}
                  disabledReason={activeTeamMemberCount === 0 ? (lang === "zh" ? "请先在团队设置中添加可用成员" : "Add an active member in team settings first") : undefined}
                  onPress={onSyncRoom}
                >
                  {lang === "zh" ? "同步群聊" : "Sync room"}
                </VButton>
              </div>
            ) : linkedChatRoomPending ? (
              <VStateSurface tone="loading" density="compact" title={lang === "zh" ? "正在读取关联群聊" : "Loading linked room"} skeletonLines={1} className={styles.spaceAbove} />
            ) : linkedRoomBusy ? (
              <div className={styles.spaceAbove}>
                <p className={styles.actionCopy}>{currentTeamRound?.topic || (lang === "zh" ? "团队正在执行当前任务。" : "The team is working on the current task.")}</p>
                <VButton
                  ref={stopTriggerRef}
                  className={styles.spacedAction}
                  variant="secondary"
                  icon={<Square size={14} aria-hidden="true" />}
                  aria-label={lang === "zh" ? "停止当前团队讨论" : "Stop current team round"}
                  isPending={stopRoundPending}
                  isDisabled={stopRoundPending || linkedRoomDetail?.status === "stopping"}
                  onPress={stopRound}
                >
                  {stopRoundPending || linkedRoomDetail?.status === "stopping"
                    ? (lang === "zh" ? "停止中" : "Stopping")
                    : (lang === "zh" ? "停止本轮" : "Stop round")}
                </VButton>
              </div>
            ) : activeTeamMemberCount === 0 ? (
              <p className={styles.spacedCopy}>{lang === "zh" ? "请先在团队设置中添加可用成员。" : "Add an active member in team settings first."}</p>
            ) : (
              <form className={styles.form} onSubmit={startRound}>
                <label htmlFor="team-home-round-topic" className={styles.label}>
                  {lang === "zh" ? "本轮任务" : "Round task"}
                  <VTextarea
                    id="team-home-round-topic"
                    value={teamTaskTopic}
                    minRows={3}
                    maxLength={1000}
                    placeholder={lang === "zh" ? "写下团队本轮要完成的任务" : "Describe what the team should complete"}
                    onChange={(event) => onTeamTaskTopicChange(event.currentTarget.value)}
                  />
                </label>
                <VButton className={styles.startAction} type="submit" isPending={startRoundPending} isDisabled={!canStartTeamRound || startRoundPending} icon={<Play size={14} aria-hidden="true" />}>
                  {startRoundPending ? (lang === "zh" ? "启动中" : "Starting") : (selectedTeam?.teamTemplateId === "dev-team" ? (lang === "zh" ? "启动开发轮次" : "Start development round") : (lang === "zh" ? "启动团队讨论" : "Start team round"))}
                </VButton>
              </form>
            )}

            {startRoundError ? <p className={styles.error} role="alert">{startRoundError.message}</p> : null}
            {stopRoundError ? <p className={styles.error} role="alert">{stopRoundError.message}</p> : null}
          </section>
        </aside>;
  const canvasOpen = Boolean(props.workspace && homeView === "canvas" && !nativeConversationOpen);
  const nativeInspector = memberConversation && selectedMember ? <section className={styles.memberInspector}>
    <h3 className={styles.inspectorHeading}>{selectedMemberDisplay?.name}</h3><p>{selectedMemberDisplay?.role}</p><p className={styles.inspectorQuiet}>{selectedMember.purpose}</p>
  </section> : <div className={styles.nativeInspector}>
    <section><h3 className={styles.inspectorHeading}>{lang === "zh" ? "当前任务" : "Current task"}</h3><p className={styles.inspectorCopy}>{currentTitle}</p><RoundStatus status={currentStatus} lang={lang} /></section>
    {currentSummary ? <section><h3 className={styles.inspectorHeading}>{lang === "zh" ? "上轮结果" : "Previous result"}</h3><p className={styles.inspectorCopy}>{currentSummary}</p></section> : null}
    {selectedTeam?.teamTemplateId === "dev-team" ? <DevTeamTaskBoard lang={lang} teamId={teamId} members={selectedTeam.members} speakingMemberId={speakingTeamMemberIdFromRoom(selectedTeam.members, linkedRoomDetail)} /> : null}
  </div>;
  const nativeBody = nativeSelectionReady ? <TeamNativeConversation lang={lang} />
    : linkedChatRoomPending ? <VStateSurface tone="loading" title={lang === "zh" ? "正在读取关联会话" : "Loading linked conversation"} skeletonLines={3} />
      : memberConversation ? <VStateSurface tone="error" title={lang === "zh" ? "成员会话尚不可用" : "Member session unavailable"}>{lang === "zh" ? "请刷新团队或同步群聊后再打开。" : "Refresh the team or sync its room."}</VStateSurface> : conversation;
  return <div className={styles.frame} data-testid="team-home-surface" data-vui-region="team-home-surface">
    <TeamWorkspaceFrame title={nativeConversationOpen ? selectedMember ? `${selectedMemberDisplay?.name} · ${lang === "zh" ? "对话" : "Conversation"}` : lang === "zh" ? "团队讨论" : "Team discussion" : lang === "zh" ? "团队主页" : "Team home"} domainRecipe="teams-organization-workbench"
      layoutId={WORKBENCH_LAYOUT_IDS.teams} resize={props.workspace?.resize}
      responsive={{ enabled: Boolean(props.workspace), rail: { label: lang === "zh" ? "团队导航" : "Team navigation" }, inspector: { label: lang === "zh" ? "本轮操作与成员详情" : "Round actions and member details" } }}
      ariaLabel={selectedTeam?.name || (lang === "zh" ? "团队主页" : "Team home")}
      railTitle={props.workspace?.teamSwitcher} rail={props.workspace?.navigation}
      inspectorTitle={canvasOpen || memberConversation ? (lang === "zh" ? "成员详情" : "Member details") : (lang === "zh" ? "本轮操作" : "Round actions")}
      mainScroll={!canvasOpen && !nativeConversationOpen} canvas={canvasOpen ? props.workspace?.canvas : nativeConversationOpen ? nativeBody : conversation}
      inspector={canvasOpen ? props.workspace?.inspector : nativeConversationOpen && nativeSelectionReady ? nativeInspector : roundActions}
      toolbar={<><VButton density="compact" variant={canvasOpen ? "primary" : "ghost"} aria-pressed={canvasOpen}
        icon={<GitBranch size={14} aria-hidden="true" />} onClick={() => { openHomeView("canvas"); onOpenOrganization(); }}>{lang === "zh" ? "画布" : "Canvas"}</VButton>
        <VButton density="compact" variant={!canvasOpen ? "primary" : "ghost"} aria-pressed={!canvasOpen} onClick={() => props.workspace ? openHomeView("conversation") : setHomeView("conversation")}>{lang === "zh" ? "成员发言" : "Messages"}</VButton>
        {roomLink ? <VRouteLinkButton density="compact" to={roomLink} variant="secondary" icon={<MessageSquare size={14} aria-hidden="true" />}>{lang === "zh" ? "打开群聊" : "Open room"}</VRouteLinkButton> : null}
        {props.workspace?.toolbar}</>} />
    <VConfirmDialog
        open={confirmStopOpen}
        onOpenChange={setConfirmStopOpen}
        title={lang === "zh" ? "停止本轮讨论？" : "Stop this round?"}
        description={lang === "zh" ? "已有发言与产出会保留。" : "Existing messages and outputs will be kept."}
        confirmLabel={lang === "zh" ? "停止本轮" : "Stop round"}
        cancelLabel={lang === "zh" ? "继续讨论" : "Keep discussing"}
        confirmPending={stopRoundPending}
        confirmDisabled={stopRoundPending || linkedRoomDetail?.status === "stopping"}
        onCloseAutoFocus={(event) => { event.preventDefault(); stopTriggerRef.current?.focus({ preventScroll: true }); }}
        onConfirm={confirmStopRound}
      />
  </div>;
}
