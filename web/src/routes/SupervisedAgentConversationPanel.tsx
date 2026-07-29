import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, CheckCircle2 } from "lucide-react";
import type { KeyboardEvent, ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import { queryKeys } from "../api/queryKeys";
import type { ConversationMessage, SessionDetail } from "../api/types";
import { LazyConversationView } from "../components/conversation/LazyConversationView";
import {
  VButton,
  VChip,
  VEmptyState,
  VLoadingValue,
  VStatusChip,
  VStatusStrip,
  VSurface,
  VToolbar,
  VTooltip,
  type VStatusTone,
} from "../components/vui";
import { fetchSessionDetailWindow } from "./chat/chatSessionDetailHelpers";
import { mergeSessionDetailMessageWindow } from "./chatSessionState";
import type { SupervisedMemberRole, SupervisedRunMember } from "./evolution/evolutionRouteModel";
import styles from "./SupervisedAgentConversationPanel.styles";

export type SupervisedAgentConversationPanelProps = {
  members: SupervisedRunMember[];
  selectedRole: SupervisedMemberRole;
  activeRole?: SupervisedMemberRole | null;
  fallbackMessages: ConversationMessage[];
  taskSummary: string;
  supplementalContent?: ReactNode;
  isLive: boolean;
  lang: "zh" | "en";
  roleLabel: (role: string | undefined) => string;
  roleDescription: (role: SupervisedMemberRole) => string;
  statusLabel: (status: string) => string;
  onSelectRole: (role: SupervisedMemberRole) => void;
  onFollowLive: () => void;
};

function roleAvatar(role: SupervisedMemberRole, lang: "zh" | "en") {
  if (lang === "en") {
    return role.slice(0, 1).toUpperCase();
  }
  if (role === "baseline") return "基";
  if (role === "baseline_rerun") return "复";
  if (role === "candidate") return "候";
  if (role === "judge") return "评";
  if (role === "reviewer") return "审";
  return "核";
}

function roleConversationTitle(role: SupervisedMemberRole, lang: "zh" | "en") {
  const titles: Record<SupervisedMemberRole, { zh: string; en: string }> = {
    baseline: { zh: "基线 Agent", en: "Baseline Agent" },
    baseline_rerun: { zh: "独立复跑", en: "Clean-room rerun" },
    candidate: { zh: "候选 Agent", en: "Candidate Agent" },
    judge: { zh: "评分 Agent", en: "Judge Agent" },
    reviewer: { zh: "审查 Agent", en: "Review Agent" },
    auditor: { zh: "审计 Agent", en: "Audit Agent" },
  };
  return titles[role][lang];
}

function memberStatusLabel(
  status: string,
  lang: "zh" | "en",
  statusLabel: (status: string) => string,
) {
  if (status === "configured") {
    return lang === "zh" ? "已配置" : "Ready";
  }
  if (status === "missing") {
    return lang === "zh" ? "未配置" : "Missing";
  }
  if (status === "active") {
    return lang === "zh" ? "现场" : "Live";
  }
  return statusLabel(status);
}

function memberStatusTone(status: string, active: boolean): VStatusTone {
  if (active) {
    return "accent";
  }
  const normalized = status.trim().toLowerCase();
  if (["configured", "ready", "completed", "succeeded", "success"].includes(normalized)) {
    return "success";
  }
  if (["missing", "failed", "error", "blocked"].includes(normalized)) {
    return "danger";
  }
  if (["waiting", "pending", "queued", "review"].includes(normalized)) {
    return "warning";
  }
  if (["active", "running", "streaming"].includes(normalized)) {
    return "accent";
  }
  return "neutral";
}

function queryErrorMessage(error: unknown, lang: "zh" | "en") {
  const detail = error instanceof Error ? error.message : String(error || "");
  if (lang === "zh") {
    return detail ? `完整会话暂时无法刷新：${detail}` : "完整会话暂时无法刷新。";
  }
  return detail ? `The full session could not refresh: ${detail}` : "The full session could not refresh.";
}

function conversationDuration(messages: ConversationMessage[]) {
  const timestamps = messages
    .map((message) => Date.parse(message.timestamp))
    .filter((timestamp) => Number.isFinite(timestamp));
  if (timestamps.length < 2) {
    return "--";
  }
  const elapsedSeconds = Math.max(
    0,
    Math.round((Math.max(...timestamps) - Math.min(...timestamps)) / 1_000),
  );
  if (elapsedSeconds < 60) {
    return `${elapsedSeconds}s`;
  }
  const minutes = Math.floor(elapsedSeconds / 60);
  const seconds = elapsedSeconds % 60;
  if (minutes < 60) {
    return seconds ? `${minutes}m ${seconds}s` : `${minutes}m`;
  }
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return remainingMinutes ? `${hours}h ${remainingMinutes}m` : `${hours}h`;
}

export function SupervisedAgentConversationPanel({
  members,
  selectedRole,
  activeRole,
  fallbackMessages,
  taskSummary,
  supplementalContent,
  isLive,
  lang,
  roleLabel,
  roleDescription,
  statusLabel,
  onSelectRole,
  onFollowLive,
}: SupervisedAgentConversationPanelProps) {
  const navigate = useNavigate();
  const selectedMember = members.find((member) => member.role === selectedRole) ?? members[0];
  const selectedChatRoute = selectedMember?.chatRoute;
  const sessionId = String(selectedMember?.conversationSession?.conversationSessionId || "").trim();
  const sessionDetailQuery = useQuery<SessionDetail>({
    queryKey: queryKeys.session(sessionId || "none"),
    enabled: Boolean(sessionId),
    queryFn: ({ signal }) => fetchSessionDetailWindow(sessionId, { messageLimit: 80, signal }),
    structuralSharing: (previous, next) =>
      mergeSessionDetailMessageWindow(previous as SessionDetail | undefined, next as SessionDetail),
    refetchInterval: isLive ? 2_000 : false,
    refetchIntervalInBackground: false,
    retry: false,
  });
  const detail = sessionDetailQuery.data?.id === sessionId ? sessionDetailQuery.data : undefined;
  const messages = detail?.messages?.length ? detail.messages : fallbackMessages;
  const messageCount = Math.max(detail?.messageWindow?.totalMessages ?? 0, messages.length);
  const duration = conversationDuration(messages);
  const assistantDisplayName = detail?.agentDisplayName || selectedMember?.name || roleLabel(selectedRole);
  const phase = detail?.currentPhase
    || detail?.status
    || selectedMember?.conversationSession?.status
    || selectedMember?.status
    || "idle";
  const selectedRawStatus = selectedMember?.conversationSession?.status
    || selectedMember?.status
    || "idle";
  const selectedStatus = memberStatusLabel(
    selectedRawStatus,
    lang,
    statusLabel,
  );
  const selectedActive = isLive && selectedRole === activeRole;
  const selectedTabId = `supervised-agent-tab-${selectedRole}`;
  const selectedPanelId = `supervised-agent-panel-${selectedRole}`;
  const emptyTitle = sessionId
    ? lang === "zh" ? `${assistantDisplayName} 暂无可展示消息` : `${assistantDisplayName} has no visible messages`
    : lang === "zh" ? `${assistantDisplayName} 尚未启动` : `${assistantDisplayName} has not started`;
  const emptyCopy = sessionId
    ? lang === "zh"
      ? "会话已建立，等待该 Agent 产生第一条可展示消息。"
      : "The session exists and is waiting for its first visible message."
    : lang === "zh"
      ? "启动一轮监督进化后，这里会显示该 Agent 的真实会话轨迹；不会借用其他 Agent 的消息。"
      : "Start a supervised evolution run to show this Agent's real session without borrowing another Agent's messages.";
  const handleTabKeyDown = (
    event: KeyboardEvent<HTMLButtonElement>,
    memberIndex: number,
  ) => {
    let nextIndex: number | null = null;
    if (event.key === "ArrowRight") {
      nextIndex = (memberIndex + 1) % members.length;
    } else if (event.key === "ArrowLeft") {
      nextIndex = (memberIndex - 1 + members.length) % members.length;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = members.length - 1;
    }
    if (nextIndex === null) {
      return;
    }
    const nextRole = members[nextIndex]?.role;
    if (!nextRole) {
      return;
    }
    event.preventDefault();
    onSelectRole(nextRole);
    requestAnimationFrame(() => {
      document.getElementById(`supervised-agent-tab-${nextRole}`)?.focus();
    });
  };

  return (
    <div
      className={styles.root}
      data-supervised-agent-conversation-panel
      data-vui-recipe="supervised-agent-conversation"
    >
      <div className={styles.tabRail} role="tablist" aria-label={lang === "zh" ? "选择 Agent 对话" : "Select Agent conversation"}>
        {members.map((member, memberIndex) => {
          const selected = member.role === selectedRole;
          const active = isLive && member.role === activeRole;
          const memberRawStatus = member.conversationSession?.status || member.status;
          const memberStatus = memberStatusLabel(
            memberRawStatus,
            lang,
            statusLabel,
          );
          return (
            <VButton
              key={member.role}
              type="button"
              contentLayout="plain"
              density="normal"
              variant={selected ? "primary" : "secondary"}
              className={styles.tabButton}
              role="tab"
              id={`supervised-agent-tab-${member.role}`}
              aria-controls={`supervised-agent-panel-${member.role}`}
              aria-selected={selected}
              tabIndex={selected ? 0 : -1}
              onKeyDown={(event) => handleTabKeyDown(event, memberIndex)}
              onPress={() => onSelectRole(member.role)}
            >
              <span className={styles.tabLayout}>
                <span className={styles.avatar} aria-hidden="true">{roleAvatar(member.role, lang)}</span>
                <span className={styles.tabCopy}>
                  <span className={styles.tabTitle}>{roleConversationTitle(member.role, lang)}</span>
                  <span className={styles.tabSubtitle}>{roleDescription(member.role)}</span>
                </span>
                <VStatusChip
                  className={styles.tabStatus}
                  tone={memberStatusTone(memberRawStatus, active)}
                >
                  {active ? (lang === "zh" ? "现场" : "Live") : memberStatus}
                </VStatusChip>
              </span>
            </VButton>
          );
        })}
      </div>

      <VSurface
        as="section"
        className={styles.sessionSurface}
        data-vui="supervised-agent-conversation-surface"
        elevation="panel"
        padding="none"
        tone="panel"
        role="tabpanel"
        id={selectedPanelId}
        aria-labelledby={selectedTabId}
      >
        <header className={styles.selectedHeader}>
          <div className={styles.selectedIdentity}>
            <span className={styles.selectedAvatar} aria-hidden="true">{roleAvatar(selectedRole, lang)}</span>
            <div className={styles.selectedCopy}>
              <div className={styles.selectedTitleRow}>
                <h3 className={styles.selectedTitle}>{assistantDisplayName}</h3>
                <VChip className={styles.identityChip} tone="neutral">
                  {roleLabel(selectedRole)}
                </VChip>
                <VStatusChip
                  className={styles.identityChip}
                  tone={memberStatusTone(selectedRawStatus, selectedActive)}
                >
                  {selectedActive ? (lang === "zh" ? "现场" : "Live") : selectedStatus}
                </VStatusChip>
              </div>
              <p className={styles.selectedDescription}>{roleDescription(selectedRole)}</p>
            </div>
          </div>
          <dl
            className={styles.selectedFacts}
            aria-label={lang === "zh" ? "当前 Agent 会话信息" : "Current Agent session facts"}
          >
            <div className={styles.factCell}>
              <dt className={styles.factLabel}>{lang === "zh" ? "会话" : "Session"}</dt>
              <dd className={styles.factValue}>
                <VTooltip content={sessionId || (lang === "zh" ? "尚无会话" : "No session")} width="wide">
                  <span tabIndex={0}>{sessionId || "--"}</span>
                </VTooltip>
              </dd>
            </div>
            <div className={styles.factCell}>
              <dt className={styles.factLabel}>{lang === "zh" ? "模型" : "Model"}</dt>
              <dd className={styles.factValue}>
                <VTooltip content={selectedMember?.modelId || selectedMember?.model || "--"} width="wide">
                  <span tabIndex={0}>{selectedMember?.model || "--"}</span>
                </VTooltip>
              </dd>
            </div>
            <div className={styles.factCell}>
              <dt className={styles.factLabel}>{lang === "zh" ? "耗时" : "Duration"}</dt>
              <dd className={styles.factValue}>{duration}</dd>
            </div>
            <div className={styles.factCell}>
              <dt className={styles.factLabel}>{lang === "zh" ? "消息" : "Messages"}</dt>
              <dd className={styles.factValue}>
                {lang === "zh" ? `${messageCount} 条` : `${messageCount}`}
              </dd>
            </div>
          </dl>
        </header>

        <VToolbar
          ariaLabel={lang === "zh" ? "Agent 会话工具栏" : "Agent conversation toolbar"}
          className={styles.timelineToolbar}
        >
          <div className={styles.conversationContract}>
            <VStatusChip className={styles.contractChip} tone="success">
              <CheckCircle2 size={14} />
              {lang === "zh" ? "统一消息链路" : "Unified message chain"}
            </VStatusChip>
            <small className={styles.contractMeta}>
              ConversationView · {lang === "zh" ? "标准消息 DTO" : "standard message DTO"}
            </small>
          </div>
          <div className={styles.toolbarActions}>
            {isLive && activeRole && selectedRole !== activeRole ? (
              <VButton
                type="button"
                className={styles.compactAction}
                variant="primary"
                onPress={onFollowLive}
              >
                {lang === "zh" ? "跟随现场" : "Follow live"}
              </VButton>
            ) : null}
            {selectedChatRoute ? (
              <VButton
                type="button"
                className={styles.sessionAction}
                trailingIcon={<ArrowUpRight size={13} aria-hidden="true" />}
                variant="secondary"
                onPress={() => navigate(selectedChatRoute)}
              >
                {lang === "zh" ? "完整会话" : "Full session"}
              </VButton>
            ) : null}
          </div>
        </VToolbar>

        <div className={styles.body} aria-live="polite">
          {sessionDetailQuery.isError ? (
            <VStatusStrip
              className={styles.queryNotice}
              role="status"
              items={[{
                label: lang === "zh" ? "会话" : "Session",
                value: queryErrorMessage(sessionDetailQuery.error, lang),
                tone: "danger",
              }]}
            />
          ) : null}
          {messages.length > 0 ? (
            <LazyConversationView
              sessionId={sessionId || `${selectedRole}-supervised`}
              className={styles.conversation}
              density="compact"
              title={assistantDisplayName}
              phase={phase}
              messages={messages}
              assistantDisplayName={assistantDisplayName}
              userDisplayName={lang === "zh" ? "监督任务" : "Supervised task"}
              taskSummary={detail?.taskSummary || taskSummary}
              defaultFileContext={detail?.defaultFileContext || "supervised-evolution"}
              summaryItems={[]}
              showHeader={false}
              showSessionOverview={Boolean(supplementalContent)}
              supplementalContent={supplementalContent}
              showComposer={false}
              processDisplayMode="trace"
              autoScrollToLatest={true}
              composerValue=""
              composerPlaceholder={lang === "zh" ? "监督进化会话只读" : "Supervised conversation is read-only"}
              composerDisabled={true}
              composerPending={false}
              onComposerChange={() => undefined}
              onSubmit={() => undefined}
              fallback={(
                <div className={styles.loading}>
                  <VLoadingValue label={lang === "zh" ? "正在加载统一对话前端" : "Loading conversation"} />
                  <span>{lang === "zh" ? "正在加载统一对话前端…" : "Loading conversation…"}</span>
                </div>
              )}
            />
          ) : sessionDetailQuery.isLoading ? (
            <div className={styles.loading}>
              <VLoadingValue label={lang === "zh" ? "正在加载 Agent 会话" : "Loading Agent session"} />
              <span>{lang === "zh" ? "正在加载 Agent 会话…" : "Loading Agent session…"}</span>
            </div>
          ) : (
            <VEmptyState
              className={styles.empty}
              icon={<span className={styles.emptyAvatar} aria-hidden="true">{roleAvatar(selectedRole, lang)}</span>}
              title={emptyTitle}
            >
              {emptyCopy}
            </VEmptyState>
          )}
        </div>
      </VSurface>
    </div>
  );
}
