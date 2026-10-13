import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { BellRing, UsersRound } from "lucide-react";

import { kernelTaskCenterHref } from "../../api/kernel";
import { isProjectAgentBusEventRevoked } from "../../api/projectAgentBus";
import type {
  ProjectAgentBusEvent,
  ProjectAgentBusTimeline,
} from "../../api/types";
import { VButton, VContextualHint, VNativeInput } from "../../components/vui";
import type { ChatMentionTarget } from "../chatMentionTokens";
import { ProgressiveRegionSkeleton } from "../shared/ProgressiveRegionSkeleton";
import { ChatMessageChromeHeader } from "./ChatMessageChromeHeader";
import { ChatMentionedText } from "./ChatGroupMessagePresentation";
import styles from "./ChatGroupCenterSurface.styles";

export type ChatProjectBusSurfaceProps = {
  lang: "zh" | "en";
  projectBusTimeline: ProjectAgentBusTimeline | null | undefined;
  projectBusEvents: ProjectAgentBusEvent[];
  projectBusDraft: string;
  projectBusInterruptTargets: boolean;
  projectBusRefreshing: boolean;
  projectBusRefreshError: string;
  projectBusSendPending: boolean;
  projectBusRevokePending: boolean;
  projectBusInitialLoading: boolean;
  groupRoomActionError: string;
  userDisplayName: string;
  chatMentionTargets: ChatMentionTarget[];
  composerLeadingControl?: ReactNode;
  formatTime: (value: string) => string;
  onProjectBusDraftChange: (value: string) => void;
  onProjectBusInterruptTargetsChange: (value: boolean) => void;
  onRefreshProjectBus: () => void;
  onSendProjectBusMessage: () => void;
  onRevokeProjectBusMessage: (eventId: string) => void;
  onOpenMentionTarget: (target: ChatMentionTarget) => void;
};

export function ChatProjectBusSurface({
  lang,
  projectBusTimeline,
  projectBusEvents,
  projectBusDraft,
  projectBusInterruptTargets,
  projectBusRefreshing,
  projectBusRefreshError,
  projectBusSendPending,
  projectBusRevokePending,
  projectBusInitialLoading,
  groupRoomActionError,
  userDisplayName,
  chatMentionTargets,
  composerLeadingControl,
  formatTime,
  onProjectBusDraftChange,
  onProjectBusInterruptTargetsChange,
  onRefreshProjectBus,
  onSendProjectBusMessage,
  onRevokeProjectBusMessage,
  onOpenMentionTarget,
}: ChatProjectBusSurfaceProps) {
  return (
    <div className={styles.groupConversationFrame}>
      <ChatMessageChromeHeader
        className={styles.groupConversationHeader}
        density="surface"
        titleRowClassName={styles.groupConversationTitleRow}
        eyebrow={(
          <p>{lang === "zh" ? "全局广播" : "Project-wide broadcast"}</p>
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
            {projectBusTimeline
              ? `${projectBusTimeline.activeAgentCount} ${lang === "zh" ? "位 active Agent" : "active agents"}`
              : (lang === "zh" ? "正在统计 active Agent" : "Counting active agents")}
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
