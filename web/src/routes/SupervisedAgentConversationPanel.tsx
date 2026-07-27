import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight } from "lucide-react";
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

function queryErrorMessage(error: unknown, lang: "zh" | "en") {
  const detail = error instanceof Error ? error.message : String(error || "");
  if (lang === "zh") {
    return detail ? `完整会话暂时无法刷新：${detail}` : "完整会话暂时无法刷新。";
  }
  return detail ? `The full session could not refresh: ${detail}` : "The full session could not refresh.";
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
  const assistantDisplayName = detail?.agentDisplayName || selectedMember?.name || roleLabel(selectedRole);
  const phase = detail?.currentPhase
    || detail?.status
    || selectedMember?.conversationSession?.status
    || selectedMember?.status
    || "idle";
  const selectedStatus = statusLabel(
    selectedMember?.conversationSession?.status
    || selectedMember?.status
    || "idle",
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
          const memberStatus = statusLabel(member.conversationSession?.status || member.status);
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
                  <span className={styles.tabTitle}>{member.name}</span>
                  <span className={styles.tabSubtitle}>
                    <span>{roleLabel(member.role)}</span>
                    <span className={active ? `${styles.tabStatus} ${styles.tabStatusActive}` : styles.tabStatus}>
                      {active ? (lang === "zh" ? "现场" : "Live") : memberStatus}
                    </span>
                  </span>
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
            <span className={styles.avatar} aria-hidden="true">{roleAvatar(selectedRole, lang)}</span>
            <div className={styles.selectedCopy}>
              <div className={styles.selectedTitle}>{assistantDisplayName}</div>
              <div className={styles.selectedMeta}>
                <span>{roleLabel(selectedRole)}</span>
                <span className={styles.selectedDescription}>{roleDescription(selectedRole)}</span>
                <span>{selectedStatus}</span>
                <VTooltip content={selectedMember?.modelId || selectedMember?.model || "--"} width="wide">
                  <span className={styles.selectedMetaValue} tabIndex={0}>{selectedMember?.model || "--"}</span>
                </VTooltip>
                <VTooltip content={sessionId || (lang === "zh" ? "尚无会话" : "No session")} width="wide">
                  <span className={styles.selectedMetaValue} tabIndex={0}>{sessionId || "--"}</span>
                </VTooltip>
              </div>
            </div>
          </div>
          <div className={styles.selectedActions}>
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
        </header>

        <div className={styles.body}>
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
