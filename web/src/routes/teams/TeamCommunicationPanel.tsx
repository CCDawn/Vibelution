import { Play, Send } from "lucide-react";
import { Link } from "react-router-dom";

import { kernelTaskCenterHref } from "../../api/kernel";
import { isProjectAgentBusEventRevoked } from "../../api/projectAgentBus";
import type {
  ChatRoomDetail,
  ChatRoomRound,
  ProjectAgentBusEvent,
  Team,
} from "../../api/types";
import {
  VNativeButton,
  VNativeInput,
  VNativeTextarea,
  VStateSurface,
} from "../../components/vui";
import { RESEARCH_TEAM_ID } from "../TeamsRoute.canvasData";
import shellStyles from "../TeamsRoute.styles";
import researchRouteStyles from "../TeamsRoute.research.styles";
import { formatTime } from "./source-collection/presentationModel";
import { teamChatRoomRoute } from "./researchStageAgentPresentation";
import { teamWorkspaceRoute } from "./researchWorkspaceModel";
import { chatRoomStatusLabel } from "./workflowPresentation";

const styles = {
  ...shellStyles,
  ...researchRouteStyles,
} as Record<string, string>;

export type TeamCommunicationPanelProps = {
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
  startRoundResult: ChatRoomDetail | undefined;
  startRoundError: Error | null;
  onStartTeamRound: (payload: {
    roomId: string;
    teamId: string;
    topic: string;
    mode: string;
    purpose: string;
  }) => void;
  teamMessage: string;
  onTeamMessageChange: (value: string) => void;
  teamInterrupt: boolean;
  onTeamInterruptChange: (value: boolean) => void;
  activeTeamMemberCount: number;
  messagePending: boolean;
  messageResult: ProjectAgentBusEvent | undefined;
  messageError: Error | null;
  onSendTeamMessage: (payload: {
    teamId: string;
    content: string;
    interruptMode: string;
  }) => void;
  teamBusEvents: ProjectAgentBusEvent[];
  projectBusPending: boolean;
  revokePendingEventId: string | null;
  revokeError: Error | null;
  onRevokeTeamMessage: (payload: { teamId: string; eventId: string }) => void;
};

/**
 * Team task round + broadcast history for board/canvas shells.
 * Extracted from TeamsRoute to dedupe identical discussion/broadcast JSX.
 */
export function TeamCommunicationPanel({
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
  startRoundResult,
  startRoundError,
  onStartTeamRound,
  teamMessage,
  onTeamMessageChange,
  teamInterrupt,
  onTeamInterruptChange,
  activeTeamMemberCount,
  messagePending,
  messageResult,
  messageError,
  onSendTeamMessage,
  teamBusEvents,
  projectBusPending,
  revokePendingEventId,
  revokeError,
  onRevokeTeamMessage,
}: TeamCommunicationPanelProps) {
  const teamBackLabel = lang === "zh" ? "返回团队页面" : "Back to team";
  const workspaceHref = teamWorkspaceRoute(selectedTeam?.teamId || RESEARCH_TEAM_ID);

  return (
    <div className={styles.researchDiscussionPanel} id="research-workflow-discussion">
      <form
        className={styles.teamTaskForm}
        onSubmit={(event) => {
          event.preventDefault();
          if (!selectedTeam?.teamId || !linkedChatRoomId || !teamTaskTopic.trim() || linkedRoomBusy) {
            return;
          }
          onStartTeamRound({
            roomId: linkedChatRoomId,
            teamId: selectedTeam.teamId,
            topic: teamTaskTopic.trim(),
            mode: linkedRoomDetail?.mode || selectedTeam.linkedChatRoom?.mode || "round_robin",
            purpose: linkedRoomDetail?.purpose || selectedTeam.linkedChatRoom?.purpose || "discussion",
          });
        }}
      >
        <div className={styles.sectionTitle}>
          <strong>{lang === "zh" ? "团队任务" : "Team task"}</strong>
          <span>
            {selectedTeam?.linkedChatRoomId
              ? linkedRoomBusy
                ? (lang === "zh" ? "群聊运行中" : "room running")
                : (lang === "zh" ? "发送到群聊 round" : "starts a room round")
              : (lang === "zh" ? "需要先同步群聊" : "sync room first")}
          </span>
        </div>
        <VNativeTextarea
          value={teamTaskTopic}
          onChange={(event) => onTeamTaskTopicChange(event.target.value)}
          placeholder={lang === "zh" ? "输入团队要协作处理的议题或任务" : "Enter a topic or task for this team"}
        />
        <VNativeButton
          type="submit"
          disabled={!canStartTeamRound || startRoundPending}
        >
          <Play size={14} />
          {startRoundPending
            ? (lang === "zh" ? "启动中" : "Starting")
            : (lang === "zh" ? "启动团队讨论" : "Start team round")}
        </VNativeButton>
        {startRoundResult ? (
          <div className={styles.messageResult}>
            <strong>{startRoundResult.rounds.length}</strong>
            <span>{lang === "zh" ? "轮讨论已写入关联群聊" : "rounds now recorded in the linked room"}</span>
            <Link to={teamChatRoomRoute(startRoundResult.roomId, workspaceHref, teamBackLabel)}>
              {lang === "zh" ? "打开群聊" : "Open room"}
            </Link>
          </div>
        ) : null}
        {startRoundError ? (
          <div className={styles.messageError}>{startRoundError.message}</div>
        ) : null}
        <section className={styles.teamRoundPanel}>
          <div className={styles.sectionTitle}>
            <strong>{lang === "zh" ? "最近团队任务" : "Latest team task"}</strong>
            <span>{linkedRoomDetail ? chatRoomStatusLabel(linkedRoomDetail.status, lang) : (lang === "zh" ? "未读取" : "not loaded")}</span>
          </div>
          {linkedChatRoomPending && linkedChatRoomId ? (
            <VStateSurface
              tone="loading"
              title={lang === "zh" ? "正在读取关联群聊" : "Loading linked room"}
              skeletonLines={2}
            />
          ) : latestTeamRound ? (
            <article className={styles.teamRoundCard}>
              <div className={styles.teamRoundHeader}>
                <strong>{latestTeamRound.topic || (lang === "zh" ? "未命名任务" : "Untitled task")}</strong>
                <span>{latestTeamRound.status}</span>
              </div>
              <p>{latestTeamRound.summary || (lang === "zh" ? "任务仍在等待成员输出。" : "Waiting for participant output.")}</p>
              <div className={styles.teamRoundMeta}>
                <span>{latestTeamRound.messages.length} messages</span>
                <span>{latestTeamRound.mode}</span>
                <span>{formatTime(latestTeamRound.updatedAt || latestTeamRound.startedAt, lang)}</span>
              </div>
              <Link to={teamChatRoomRoute(latestTeamRound.roomId, workspaceHref, teamBackLabel)}>
                {lang === "zh" ? "查看完整群聊" : "View full room"}
              </Link>
            </article>
          ) : (
            <div className={styles.empty}>
              {linkedChatRoomId
                ? (lang === "zh" ? "关联群聊还没有团队任务记录。" : "No team task rounds in the linked room yet.")
                : (lang === "zh" ? "同步群聊后可查看团队任务状态。" : "Sync a room to view team task status.")}
            </div>
          )}
          {linkedChatRoomError ? (
            <div className={styles.messageError}>{linkedChatRoomError.message}</div>
          ) : null}
        </section>
      </form>
      <form
        className={styles.teamMessageForm}
        onSubmit={(event) => {
          event.preventDefault();
          if (!selectedTeam?.teamId || !teamMessage.trim()) {
            return;
          }
          onSendTeamMessage({
            teamId: selectedTeam.teamId,
            content: teamMessage.trim(),
            interruptMode: teamInterrupt ? "interrupt_targets" : "none",
          });
        }}
      >
        <div className={styles.sectionTitle}>
          <strong>{lang === "zh" ? "团队广播" : "Team broadcast"}</strong>
          <span>{activeTeamMemberCount} active agents</span>
        </div>
        <VNativeTextarea
          value={teamMessage}
          onChange={(event) => onTeamMessageChange(event.target.value)}
          placeholder={lang === "zh" ? "发送给当前团队 active 成员" : "Send to active members of this team"}
        />
        <label className={styles.inlineToggle}>
          <VNativeInput
            type="checkbox"
            checked={teamInterrupt}
            onChange={(event) => onTeamInterruptChange(event.target.checked)}
          />
          <span>{lang === "zh" ? "打断正在直聊中的目标 Agent" : "Interrupt targeted running direct sessions"}</span>
        </label>
        <VNativeButton
          type="submit"
          disabled={!selectedTeam || !teamMessage.trim() || activeTeamMemberCount === 0 || messagePending}
        >
          <Send size={14} />
          {lang === "zh" ? "发送给团队" : "Send to team"}
        </VNativeButton>
        {messageResult ? (
          <div className={styles.messageResult}>
            <strong>{messageResult.deliveries.length}</strong>
            <span>{lang === "zh" ? "条投递已进入项目总群" : "deliveries recorded in project bus"}</span>
            {messageResult.kernel?.taskId ? (
              <Link className={styles.kernelTraceLink} to={kernelTaskCenterHref(messageResult.kernel.taskId)}>
                {lang === "zh" ? "Kernel 任务" : "Kernel Task"}
              </Link>
            ) : null}
          </div>
        ) : null}
        {messageError ? (
          <div className={styles.messageError}>{messageError.message}</div>
        ) : null}
      </form>
      <section className={styles.teamHistoryPanel}>
        <div className={styles.sectionTitle}>
          <strong>{lang === "zh" ? "最近团队广播" : "Recent team broadcasts"}</strong>
          <span>{teamBusEvents.length} events</span>
        </div>
        {projectBusPending ? (
          <VStateSurface
            tone="loading"
            title={lang === "zh" ? "正在读取项目总群" : "Loading project bus"}
            skeletonLines={2}
          />
        ) : teamBusEvents.length ? (
          <div className={styles.teamHistoryList}>
            {teamBusEvents.map((event) => {
              const revoked = isProjectAgentBusEventRevoked(event);
              const revokePending = revokePendingEventId === event.eventId;
              return (
                <article
                  key={event.eventId}
                  className={revoked ? `${styles.teamHistoryItem} ${styles.teamHistoryItemRevoked}` : styles.teamHistoryItem}
                >
                  <div className={styles.teamHistoryHeader}>
                    <strong>{event.summary || event.content}</strong>
                    <span>{revoked ? (lang === "zh" ? "已撤回" : "revoked") : event.messageType}</span>
                  </div>
                  <p>
                    {revoked
                      ? (lang === "zh"
                        ? "这条团队广播已撤回，目标 Agent 已请求停止。"
                        : "This team broadcast was revoked and target agents were asked to stop.")
                      : event.content}
                  </p>
                  <div className={styles.teamHistoryMeta}>
                    <span>{formatTime(event.createdAt, lang)}</span>
                    <span>{event.deliveries.length} deliveries</span>
                    <span>{event.interruptions.length} interrupts</span>
                    {event.kernel?.taskId ? (
                      <Link className={styles.kernelTraceLink} to={kernelTaskCenterHref(event.kernel.taskId)}>
                        {lang === "zh" ? "Kernel 任务" : "Kernel Task"}
                      </Link>
                    ) : null}
                  </div>
                  <div className={styles.deliveryList}>
                    {event.deliveries.map((delivery) => (
                      <span key={`${event.eventId}-${delivery.targetAgentId}-${delivery.inboxMessageId}`}>
                        {delivery.targetAgentCode || delivery.targetAgentName || delivery.targetAgentId}:{" "}
                        {delivery.revoked ? "revoked" : delivery.wake?.wakeStatus || delivery.status}
                      </span>
                    ))}
                  </div>
                  {event.createdBy === "user" && !revoked ? (
                    <VNativeButton
                      type="button"
                      className={styles.revokeButton}
                      disabled={revokePending}
                      onClick={() =>
                        selectedTeam?.teamId
                        && onRevokeTeamMessage({ teamId: selectedTeam.teamId, eventId: event.eventId })
                      }
                    >
                      {revokePending ? (lang === "zh" ? "撤回中" : "Revoking") : (lang === "zh" ? "撤回" : "Revoke")}
                    </VNativeButton>
                  ) : null}
                </article>
              );
            })}
          </div>
        ) : (
          <div className={styles.empty}>{lang === "zh" ? "当前团队还没有广播记录。" : "No team broadcasts yet."}</div>
        )}
        {revokeError ? (
          <div className={styles.messageError}>{revokeError.message}</div>
        ) : null}
      </section>
    </div>
  );
}
