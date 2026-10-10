import { useEffect, useRef, useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, GitBranch, MessageSquare, Play, Square } from "lucide-react";

import { queryKeys } from "../../api/queryKeys";
import type { ChatRoomDetail, ChatRoomMessage, ChatRoomRound, Team } from "../../api/types";
import { VButton, VConfirmDialog, VRouteLinkButton, VStateSurface, VStatusChip, VTextarea } from "../../components/vui";
import { ChatGroupMessageBody } from "../chat/ChatGroupMessagePresentation";
import { useGroupRoomTimeline } from "../chat/useGroupRoomTimeline";
import { DevTeamTaskBoard, speakingTeamMemberIdFromRoom } from "./DevTeamTaskBoard";
import { formatTime } from "./source-collection/presentationModel";
import { teamChatRoomRoute } from "./researchStageAgentPresentation";
import { teamWorkspaceRoute } from "./researchWorkspaceModel";

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
    <VStatusChip className="shrink-0" tone={state.tone}>{lang === "zh" ? state.zh : state.en}</VStatusChip>
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
      <p role={waitingForTimeline ? "status" : undefined} className="py-4 text-sm text-[var(--fg-tertiary)]">
        {waitingForTimeline
          ? (lang === "zh" ? "正在同步本轮发言…" : "Syncing messages for this round…")
          : (lang === "zh" ? "还没有团队任务记录。" : "No team task history yet.")}
      </p>
    );
  }
  if (!messages.length) {
    return <p className="py-4 text-sm text-[var(--fg-tertiary)]">{lang === "zh" ? "本轮暂时没有可展示的发言。" : "No visible messages in this round yet."}</p>;
  }

  return (
    <>
      <ol className="divide-y divide-[var(--vui-border-subtle)]">
        {messages.map((message) => (
          <li key={message.messageId} className="py-3.5 first:pt-1">
            <div className="flex min-w-0 items-baseline justify-between gap-3">
              <strong className="truncate text-sm font-semibold">{messageLabel(message, selectedTeam, linkedRoomDetail, lang)}</strong>
              <time className="shrink-0 text-xs text-[var(--fg-tertiary)]">{formatTime(message.timestamp, lang)}</time>
            </div>
            <div className="mt-1 min-w-0 break-words text-[15px] leading-6 text-[var(--fg-secondary)]">
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
        <VRouteLinkButton to={roomLink} variant="ghost" className="mt-2 !min-h-11 !px-0 text-sm" trailingIcon={<ArrowUpRight size={14} aria-hidden="true" />}>
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
  const queryClient = useQueryClient();
  const [confirmStopOpen, setConfirmStopOpen] = useState(false);
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

  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col bg-[var(--vui-surface-panel)]" data-testid="team-home-surface">
      <header className="flex shrink-0 flex-wrap items-start justify-between gap-4 border-b border-[var(--vui-border-subtle)] px-7 py-5 max-[600px]:flex-col max-[600px]:px-4 max-[600px]:py-4">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-[var(--fg-tertiary)]">{lang === "zh" ? "当前任务" : "Current task"}</p>
          <h2 className="mt-1 break-words text-xl font-semibold leading-7 tracking-normal max-[600px]:text-lg">{currentTitle}</h2>
          <div className="mt-2 flex flex-wrap items-center gap-2.5">
            <RoundStatus status={currentStatus} lang={lang} />
            {currentTeamRound?.updatedAt || currentTeamRound?.startedAt ? (
              <time className="text-xs text-[var(--fg-tertiary)]">{lang === "zh" ? "更新于" : "Updated"} {formatTime(currentTeamRound.updatedAt || currentTeamRound.startedAt, lang)}</time>
            ) : null}
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {roomLink ? (
            <VRouteLinkButton to={roomLink} variant="secondary" className="!min-h-11" icon={<MessageSquare size={15} aria-hidden="true" />}>
              {lang === "zh" ? "打开群聊" : "Open room"}
            </VRouteLinkButton>
          ) : null}
          <VButton variant="ghost" className="!min-h-11" icon={<GitBranch size={15} aria-hidden="true" />} onPress={onOpenOrganization}>
            {lang === "zh" ? "组织结构" : "Organization"}
          </VButton>
        </div>
      </header>

      <main className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_300px] max-[900px]:grid-cols-1 max-[900px]:overflow-y-auto">
        <div className="min-h-0 min-w-0 overflow-y-auto px-7 py-5 max-[900px]:min-h-max max-[900px]:overflow-visible max-[600px]:px-4 max-[600px]:py-4">
          {selectedTeam?.teamTemplateId === "dev-team" && selectedTeam.teamId ? (
            <section className="mb-6 border-b border-[var(--vui-border-subtle)] pb-5" aria-label={lang === "zh" ? "共享任务板" : "Shared task board"}>
              <DevTeamTaskBoard
                lang={lang}
                teamId={selectedTeam.teamId}
                members={selectedTeam.members ?? []}
                speakingMemberId={speakingTeamMemberIdFromRoom(selectedTeam.members ?? [], linkedRoomDetail)}
              />
            </section>
          ) : null}
          {currentSummary ? (
            <section aria-labelledby="team-home-round-result" className="pb-5">
              {deliveryOnlySummary ? (
                <details className="text-sm">
                  <summary className="cursor-pointer font-medium text-[var(--fg-tertiary)]">{lang === "zh" ? "轮次结果" : "Round result"}</summary>
                  <p className="mt-2 whitespace-pre-wrap break-words leading-6 text-[var(--fg-secondary)]">{currentSummary}</p>
                </details>
              ) : (
                <>
                  <h3 id="team-home-round-result" className="text-sm font-semibold text-[var(--fg-tertiary)]">{lang === "zh" ? "本轮结论" : "Round conclusion"}</h3>
                  <p className="mt-2 whitespace-pre-wrap break-words text-base leading-7 text-[var(--fg-secondary)]">{currentSummary}</p>
                </>
              )}
            </section>
          ) : null}

          <section aria-labelledby="team-home-recent-messages" className={currentSummary ? "border-t border-[var(--vui-border-subtle)] pt-5" : ""}>
            <div className="flex items-center gap-2">
              <MessageSquare size={15} className="text-[var(--fg-tertiary)]" aria-hidden="true" />
              <h3 id="team-home-recent-messages" className="text-base font-semibold">{lang === "zh" ? "近期发言" : "Recent messages"}</h3>
            </div>

            {linkedChatRoomPending && linkedChatRoomId ? (
              <VStateSurface tone="loading" density="compact" title={lang === "zh" ? "正在读取群聊" : "Loading room"} skeletonLines={2} className="mt-3" />
            ) : linkedChatRoomError ? (
              <VStateSurface tone="error" density="compact" title={lang === "zh" ? "群聊读取失败" : "Could not load room"} className="mt-3">
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

        <aside className="min-w-0 border-l border-[var(--vui-border-subtle)] bg-[var(--vui-surface-rail)] px-5 py-5 max-[900px]:border-l-0 max-[900px]:border-t max-[600px]:px-4 max-[600px]:py-4">
          <section aria-labelledby="team-home-round-action">
            <h3 id="team-home-round-action" className="text-base font-semibold">
              {linkedRoomBusy ? (lang === "zh" ? "本轮正在运行" : "Round in progress") : (lang === "zh" ? "开始下一轮" : "Start next round")}
            </h3>

            {!linkedChatRoomId ? (
              <div className="mt-3">
                <p className="text-sm leading-6 text-[var(--fg-secondary)]">{lang === "zh" ? "还没有关联群聊" : "No linked room"}</p>
                <VButton
                  className="mt-3 !min-h-11"
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
              <VStateSurface tone="loading" density="compact" title={lang === "zh" ? "正在读取关联群聊" : "Loading linked room"} skeletonLines={1} className="mt-3" />
            ) : linkedRoomBusy ? (
              <div className="mt-3">
                <p className="text-sm leading-6 text-[var(--fg-secondary)]">{currentTeamRound?.topic || (lang === "zh" ? "团队正在执行当前任务。" : "The team is working on the current task.")}</p>
                <VButton
                  ref={stopTriggerRef}
                  className="mt-3 !min-h-11"
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
              <p className="mt-3 text-sm leading-6 text-[var(--fg-secondary)]">{lang === "zh" ? "请先在团队设置中添加可用成员。" : "Add an active member in team settings first."}</p>
            ) : (
              <form className="mt-3 grid gap-3" onSubmit={startRound}>
                <label htmlFor="team-home-round-topic" className="grid gap-1.5 text-sm font-medium">
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
                <VButton className="!min-h-11 justify-self-start" type="submit" isPending={startRoundPending} isDisabled={!canStartTeamRound || startRoundPending} icon={<Play size={14} aria-hidden="true" />}>
                  {startRoundPending ? (lang === "zh" ? "启动中" : "Starting") : (selectedTeam?.teamTemplateId === "dev-team" ? (lang === "zh" ? "启动开发轮次" : "Start development round") : (lang === "zh" ? "启动团队讨论" : "Start team round"))}
                </VButton>
              </form>
            )}

            {startRoundError ? <p className="mt-3 text-sm text-[var(--state-error)]" role="alert">{startRoundError.message}</p> : null}
            {stopRoundError ? <p className="mt-3 text-sm text-[var(--state-error)]" role="alert">{stopRoundError.message}</p> : null}
          </section>
        </aside>
      </main>
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
    </div>
  );
}
