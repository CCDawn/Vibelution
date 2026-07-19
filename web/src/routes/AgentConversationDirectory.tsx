import type { AgentInstance, SessionSummary } from "../api/types";
import { VButton } from "../components/vui";
import styles from "./AgentConversationDirectory.styles";

export type AgentConversationDirectoryProps = {
  activeAgentId: string;
  agents: AgentInstance[];
  avatarInitials: (agentCode?: string, name?: string, fallback?: string) => string;
  filterText: string;
  formatTime: (value: string) => string;
  lang: "zh" | "en";
  resolveModelLabel: (modelId: string) => string | undefined;
  sessions: SessionSummary[];
  onOpenAgent: (agent: AgentInstance) => void;
};

function isVisibleChatAgent(agent: AgentInstance) {
  const visibility = String(agent.conversationIndexVisibility || "").trim();
  const kind = String(agent.conversationIndexKind || "").trim();
  return (
    String(agent.kind || "").trim() === "persistent"
    && String(agent.status || "").trim() !== "archived"
    && visibility !== "hidden"
    && kind !== "team_agent"
  );
}

function isAgentMatch(agent: AgentInstance, filterText: string) {
  const query = String(filterText || "").trim().toLocaleLowerCase();
  if (!query) {
    return true;
  }
  return [agent.displayName, agent.agentCode, agent.roleKey]
    .join(" ")
    .toLocaleLowerCase()
    .includes(query);
}

function agentStateClass(agent: AgentInstance) {
  const state = String(agent.status || "").trim().toLowerCase();
  if (state.includes("running") || state.includes("active") || state.includes("处理中")) {
    return styles.agentStatusRunning;
  }
  if (state.includes("error") || state.includes("failed") || state.includes("失败")) {
    return styles.agentStatusError;
  }
  return "";
}

export function AgentConversationDirectory({
  activeAgentId,
  agents,
  avatarInitials,
  filterText,
  formatTime,
  lang,
  resolveModelLabel,
  sessions,
  onOpenAgent,
}: AgentConversationDirectoryProps) {
  const visibleAgents = agents.filter(isVisibleChatAgent).filter((agent) => isAgentMatch(agent, filterText));
  const sessionCountByAgentId = new Map<string, number>();
  const latestSessionByAgentId = new Map<string, SessionSummary>();
  for (const session of sessions) {
    const agentId = String(session.agentId || "").trim();
    if (!agentId) {
      continue;
    }
    sessionCountByAgentId.set(agentId, (sessionCountByAgentId.get(agentId) || 0) + 1);
    const previous = latestSessionByAgentId.get(agentId);
    if (!previous || String(previous.updatedAt || previous.lastActive || "") < String(session.updatedAt || session.lastActive || "")) {
      latestSessionByAgentId.set(agentId, session);
    }
  }

  return (
    <nav className={styles.agentDirectory} aria-label={lang === "zh" ? "Agent 管理" : "Agent management"}>
      <div className={styles.agentDirectoryHeader}>
        <span>{lang === "zh" ? "Agent 管理" : "Agent management"}</span>
        <span className={styles.agentDirectoryCount}>{visibleAgents.length}</span>
      </div>
      {visibleAgents.length ? (
        <div className={styles.agentDirectoryList}>
          {visibleAgents.map((agent) => {
            const agentId = String(agent.agentId || "").trim();
            const latestSession = latestSessionByAgentId.get(agentId);
            const modelId = String(agent.llmBindings?.dialogue?.modelId || "").trim();
            const modelLabel = resolveModelLabel(modelId) || modelId;
            const sessionCount = sessionCountByAgentId.get(agentId) || 0;
            const active = agentId === activeAgentId;
            const displayName = String(agent.displayName || agent.agentCode || agentId).trim();
            const avatarUrl = String(agent.avatarImageUrl || "").trim();
            return (
              <VButton
                key={agentId}
                type="button"
                contentLayout="plain"
                className={[styles.agentRow, active ? styles.agentRowActive : ""].filter(Boolean).join(" ")}
                aria-current={active ? "page" : undefined}
                onPress={() => onOpenAgent(agent)}
              >
                <span className={styles.agentAvatar} aria-hidden="true">
                  {avatarUrl ? <img className={styles.agentAvatarImage} src={avatarUrl} alt="" /> : avatarInitials(agent.agentCode, displayName, agentId)}
                </span>
                <span className={styles.agentCopy}>
                  <span className={styles.agentTitleRow}>
                    <span className={styles.agentTitle}>{displayName}</span>
                    <span className={[styles.agentStatus, agentStateClass(agent)].filter(Boolean).join(" ")} />
                  </span>
                  <span className={styles.agentMeta}>
                    <span className={styles.agentMetaItem}>{modelLabel || (lang === "zh" ? "未配置模型" : "No model")}</span>
                    <span className={styles.agentMetaCount}>{lang === "zh" ? `${sessionCount} 个会话` : `${sessionCount} sessions`}</span>
                    {latestSession ? <time className={styles.agentMetaItem}>{formatTime(latestSession.updatedAt || latestSession.lastActive)}</time> : null}
                  </span>
                </span>
              </VButton>
            );
          })}
        </div>
      ) : (
        <p className={styles.agentEmpty}>
          {lang === "zh" ? "暂无可用 Agent。新建 Agent 后可在其下建立多个会话。" : "No available Agents. Create an Agent, then add sessions under it."}
        </p>
      )}
    </nav>
  );
}
