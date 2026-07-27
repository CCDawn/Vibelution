import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, CheckCircle2 } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { queryKeys } from "../api/queryKeys";
import type { ConversationMessage, SessionDetail } from "../api/types";
import { LazyConversationView } from "../components/conversation/LazyConversationView";
import { VButton, VTooltip } from "../components/vui";
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
  if (role === "candidate") return "候";
  if (role === "judge") return "评";
  if (role === "reviewer") return "审";
  return "核";
}

function roleConversationTitle(role: SupervisedMemberRole, lang: "zh" | "en") {
  const titles: Record<SupervisedMemberRole, { zh: string; en: string }> = {
    baseline: { zh: "基线 Agent", en: "Baseline Agent" },
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
  const selectedMember = members.find((member) => member.role === selectedRole) ?? members[0];
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
  const selectedStatus = memberStatusLabel(
    selectedMember?.conversationSession?.status
    || selectedMember?.status
    || "idle",
    lang,
    statusLabel,
  );
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

  return (
    <div className={styles.root} data-supervised-agent-conversation-panel>
      <div className={styles.tabRail} role="tablist" aria-label={lang === "zh" ? "选择 Agent 对话" : "Select Agent conversation"}>
        {members.map((member) => {
          const selected = member.role === selectedRole;
          const active = isLive && member.role === activeRole;
          const memberStatus = memberStatusLabel(
            member.conversationSession?.status || member.status,
            lang,
            statusLabel,
          );
          return (
            <VButton
              key={member.role}
              type="button"
              contentLayout="plain"
              className={selected ? `${styles.tabButton} ${styles.tabButtonActive}` : styles.tabButton}
              role="tab"
              id={`supervised-agent-tab-${member.role}`}
              aria-controls={`supervised-agent-panel-${member.role}`}
              aria-selected={selected}
              onClick={() => onSelectRole(member.role)}
            >
              <span className={styles.tabLayout}>
                <span className={styles.avatar} aria-hidden="true">{roleAvatar(member.role, lang)}</span>
                <span className={styles.tabCopy}>
                  <span className={styles.tabTitle}>{roleConversationTitle(member.role, lang)}</span>
                  <span className={styles.tabSubtitle}>{roleDescription(member.role)}</span>
                </span>
                <span className={active ? `${styles.tabStatus} ${styles.tabStatusActive}` : styles.tabStatus}>
                  {active ? (lang === "zh" ? "现场" : "Live") : memberStatus}
                </span>
              </span>
            </VButton>
          );
        })}
      </div>

      <section
        className={styles.sessionSurface}
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
                <span className={styles.roleBadge}>{roleLabel(selectedRole)}</span>
                <span className={styles.statusBadge}>{selectedStatus}</span>
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

        <div className={styles.timelineToolbar}>
          <div className={styles.conversationContract}>
            <span className={styles.contractIcon} aria-hidden="true">
              <CheckCircle2 size={14} />
            </span>
            <span className={styles.contractCopy}>
              <strong className={styles.contractTitle}>
                {lang === "zh" ? "统一消息链路" : "Unified message chain"}
              </strong>
              <small className={styles.contractMeta}>
                ConversationView · {lang === "zh" ? "标准消息 DTO" : "standard message DTO"}
              </small>
            </span>
          </div>
          <div className={styles.toolbarActions}>
            {isLive && activeRole && selectedRole !== activeRole ? (
              <VButton type="button" className={styles.compactAction} onClick={onFollowLive}>
                {lang === "zh" ? "跟随现场" : "Follow live"}
              </VButton>
            ) : null}
            {selectedMember?.chatRoute ? (
              <Link className={styles.sessionLink} to={selectedMember.chatRoute}>
                <span>{lang === "zh" ? "完整会话" : "Full session"}</span>
                <ArrowUpRight size={13} aria-hidden="true" />
              </Link>
            ) : null}
          </div>
        </div>

        <div className={styles.body} aria-live="polite">
          {sessionDetailQuery.isError ? (
            <div className={styles.queryNotice} role="status">{queryErrorMessage(sessionDetailQuery.error, lang)}</div>
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
              processDisplayMode="answer"
              autoScrollToLatest={true}
              composerValue=""
              composerPlaceholder={lang === "zh" ? "监督进化会话只读" : "Supervised conversation is read-only"}
              composerDisabled={true}
              composerPending={false}
              onComposerChange={() => undefined}
              onSubmit={() => undefined}
              fallback={<div className={styles.loading}>{lang === "zh" ? "正在加载统一对话前端…" : "Loading conversation…"}</div>}
            />
          ) : sessionDetailQuery.isLoading ? (
            <div className={styles.loading}>{lang === "zh" ? "正在加载 Agent 会话…" : "Loading Agent session…"}</div>
          ) : (
            <div className={styles.empty}>
              <span className={styles.emptyAvatar} aria-hidden="true">{roleAvatar(selectedRole, lang)}</span>
              <strong className={styles.emptyTitle}>{emptyTitle}</strong>
              <span>{emptyCopy}</span>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
