import { ChevronDown, ChevronRight } from "lucide-react";
import { useState, type MouseEvent as ReactMouseEvent } from "react";

import type { AgentInstance, SessionSummary } from "../api/types";
import { VButton } from "../components/vui";
import { agentDisplayInfo } from "./agentDisplay";
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
  onContextMenu: (
    event: ReactMouseEvent<HTMLElement>,
    agent: AgentInstance,
    latestSession: SessionSummary | null,
  ) => void;
  onOpenAgent: (agent: AgentInstance) => void;
};

export type AgentDirectorySection = "conversation" | "special";

const DEFAULT_COLLAPSED_DIRECTORY_SECTIONS: Record<AgentDirectorySection, boolean> = {
  conversation: false,
  special: false,
};

function storedConversationIndexKind(agent: AgentInstance) {
  return String(
    agent.conversationIndexKind
    || agent.metadata?.conversationIndexKind
    || "",
  ).trim();
}

export function isVisibleDirectoryAgent(agent: AgentInstance) {
  const kind = storedConversationIndexKind(agent);
  return (
    String(agent.kind || "").trim() === "persistent"
    && String(agent.status || "").trim() !== "archived"
    && kind !== "team_agent"
  );
}

export function agentDirectorySection(agent: AgentInstance): AgentDirectorySection {
  const primaryMode = String(agent.primaryMode || "").trim();
  const roleKey = String(agent.roleKey || "").trim();
  return primaryMode === "chat" && !roleKey ? "conversation" : "special";
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
  if (state.includes("running") || state.includes("处理中")) {
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
  onContextMenu,
  onOpenAgent,
}: AgentConversationDirectoryProps) {
  const visibleAgents = agents.filter(isVisibleDirectoryAgent).filter((agent) => isAgentMatch(agent, filterText));
  const conversationAgents = visibleAgents.filter((agent) => agentDirectorySection(agent) === "conversation");
  const specialAgents = visibleAgents.filter((agent) => agentDirectorySection(agent) === "special");
  const [collapsedSections, setCollapsedSections] = useState<Record<AgentDirectorySection, boolean>>(
    DEFAULT_COLLAPSED_DIRECTORY_SECTIONS,
  );
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

  const renderAgent = (agent: AgentInstance) => {
    const agentId = String(agent.agentId || "").trim();
    const latestSession = latestSessionByAgentId.get(agentId);
    const display = agentDisplayInfo(agent, lang, { resolveModelLabel });
    const sessionCount = sessionCountByAgentId.get(agentId) || 0;
    const active = agentId === activeAgentId;
    const avatarUrl = String(agent.avatarImageUrl || "").trim();
    return (
      <VButton
        key={agentId}
        type="button"
        contentLayout="plain"
        className={[styles.agentRow, active ? styles.agentRowActive : ""].filter(Boolean).join(" ")}
        aria-current={active ? "page" : undefined}
        onContextMenu={(event) => onContextMenu(event, agent, latestSession ?? null)}
        onPress={() => onOpenAgent(agent)}
      >
        <span className={styles.agentAvatar} aria-hidden="true">
          {avatarUrl ? <img className={styles.agentAvatarImage} src={avatarUrl} alt="" /> : avatarInitials(agent.agentCode, display.name, agentId)}
        </span>
        <span className={styles.agentCopy}>
          <span className={styles.agentTitleRow}>
            <span className={styles.agentTitle}>{display.name}</span>
            <span className={[styles.agentStatus, agentStateClass(agent)].filter(Boolean).join(" ")} />
          </span>
          <span className={styles.agentMeta}>
            <span className={styles.agentMetaItem}>{display.functionLabel}</span>
            <span className={styles.agentMetaItem}>{display.modelLabel || (lang === "zh" ? "未配置模型" : "No model")}</span>
            <span className={styles.agentMetaCount}>
              {sessionCount > 0
                ? (lang === "zh" ? `${sessionCount} 个会话` : `${sessionCount} sessions`)
                : (lang === "zh" ? "点击创建会话" : "Create a session")}
            </span>
            {latestSession ? <time className={styles.agentMetaItem}>{formatTime(latestSession.updatedAt || latestSession.lastActive)}</time> : null}
          </span>
        </span>
      </VButton>
    );
  };

  const renderSection = (section: AgentDirectorySection, sectionAgents: AgentInstance[]) => {
    if (!sectionAgents.length) {
      return null;
    }
    const label = section === "conversation"
      ? (lang === "zh" ? "会话 Agent" : "Conversation Agents")
      : (lang === "zh" ? "特殊 Agent" : "Special Agents");
    const expanded = !collapsedSections[section];
    const sectionContentId = `agent-directory-section-${section}`;
    const toggleLabel = expanded
      ? (lang === "zh" ? `收起${label}` : `Collapse ${label}`)
      : (lang === "zh" ? `展开${label}` : `Expand ${label}`);
    return (
      <section className={styles.agentSection} aria-label={label}>
        <VButton
          type="button"
          contentLayout="plain"
          className={styles.agentSectionHeader}
          aria-expanded={expanded}
          aria-controls={sectionContentId}
          aria-label={toggleLabel}
          title={toggleLabel}
          onClick={() => setCollapsedSections((current) => ({ ...current, [section]: !current[section] }))}
        >
          <span className={styles.agentSectionHeaderLabel}>
            {expanded ? <ChevronDown size={14} aria-hidden="true" /> : <ChevronRight size={14} aria-hidden="true" />}
            <span>{label}</span>
          </span>
          <strong>{sectionAgents.length}</strong>
        </VButton>
        {expanded ? <div id={sectionContentId} className={styles.agentDirectoryList}>{sectionAgents.map(renderAgent)}</div> : null}
      </section>
    );
  };

  return (
    <nav className={styles.agentDirectory} aria-label={lang === "zh" ? "Agent 目录" : "Agent directory"}>
      <div className={styles.agentDirectoryHeader}>
        <span>{lang === "zh" ? "Agent" : "Agents"}</span>
        <span className={styles.agentDirectoryCount}>{visibleAgents.length}</span>
      </div>
      {visibleAgents.length ? (
        <>
          {renderSection("conversation", conversationAgents)}
          {renderSection("special", specialAgents)}
        </>
      ) : (
        <p className={styles.agentEmpty}>
          {lang === "zh" ? "暂无可用 Agent。新建 Agent 后可在其下建立多个会话。" : "No available Agents. Create an Agent, then add sessions under it."}
        </p>
      )}
    </nav>
  );
}
