import { LoaderCircle } from "lucide-react";
import { useMemo, useState, type MouseEvent as ReactMouseEvent } from "react";

import type { AgentInstance, SessionSummary, Team } from "../api/types";
import { VButton } from "../components/vui";
import { agentDisplayInfo } from "./agentDisplay";
import {
  agentDirectoryBucket,
  agentDirectorySection,
  buildAgentDirectoryPartition,
  isConversationDirectoryAgent,
  isEligibleDirectoryAgent,
  isVisibleFlatDirectoryAgent,
} from "./agentConversationDirectoryModel";
import { ConversationIndexSection } from "./ConversationIndexSection";
import { TeamConversationIndexItem } from "./GroupSessionIndexItems";
import {
  resolveAgentActivityTone,
  resolveSessionActivityTone,
  sessionActivityLabel,
  type SessionActivityTone,
} from "./sessionActivityIndicator";
import styles from "./AgentConversationDirectory.styles";

export type AgentConversationDirectoryProps = {
  activeAgentId: string;
  activeSessionId?: string | null;
  activeGroupRoomId?: string;
  agents: AgentInstance[];
  avatarInitials: (agentCode?: string, name?: string, fallback?: string) => string;
  filterText: string;
  formatTime: (value: string) => string;
  lang: "zh" | "en";
  resolveModelLabel: (modelId: string) => string | undefined;
  /** Session ids with an active runtime chat_turn (green spinner). */
  runtimeRunningSessionIds?: readonly string[];
  sessions: SessionSummary[];
  /** Session ids waiting on tool/permission approval (yellow spinner). */
  sessionIdsNeedingApproval?: readonly string[];
  statusLabel: (status: string) => string;
  teams?: Team[];
  onContextMenu: (
    event: ReactMouseEvent<HTMLElement>,
    agent: AgentInstance,
    latestSession: SessionSummary | null,
  ) => void;
  onOpenAgent: (agent: AgentInstance, latestSession: SessionSummary | null) => void;
  onOpenGroupRoom?: (roomId: string) => void;
};

export type AgentDirectorySection = "conversation" | "special";

const DEFAULT_COLLAPSED_DIRECTORY_SECTIONS: Record<AgentDirectorySection, boolean> = {
  conversation: false,
  special: false,
};

// Re-export model helpers so existing imports from this module keep working.
export {
  agentDirectoryBucket,
  agentDirectorySection,
  buildAgentDirectoryPartition,
  isConversationDirectoryAgent,
  isEligibleDirectoryAgent,
  isVisibleFlatDirectoryAgent,
};

/** @deprecated Prefer isVisibleFlatDirectoryAgent / buildAgentDirectoryPartition. */
export function isVisibleDirectoryAgent(agent: AgentInstance) {
  return isVisibleFlatDirectoryAgent(agent);
}

/**
 * Agents that appear in the flat (non-team) directory list historically.
 * Team members now live under team blocks; experiment-backed team_agent rows
 * remain discoverable via partition special orphans if needed.
 */
export function visibleDirectoryAgents(
  agents: AgentInstance[],
  sessions: SessionSummary[],
) {
  void sessions;
  return agents.filter((agent) => isVisibleFlatDirectoryAgent(agent));
}

export function agentDirectorySessionCount(
  agent: AgentInstance,
  knownSessionCount: number,
  knownSessionIds: ReadonlySet<string>,
) {
  const sessionCount = Math.max(0, knownSessionCount);
  const directSessionId = String(agent.directSessionId || "").trim();
  const directSessionVisibility = String(agent.metadata?.directSessionVisibility || "").trim();
  const hasUnindexedActiveDirectSession = (
    Boolean(directSessionId)
    && directSessionVisibility === "active_session"
    && !knownSessionIds.has(directSessionId)
  );
  return sessionCount + (hasUnindexedActiveDirectSession ? 1 : 0);
}

function agentActivityClass(tone: SessionActivityTone) {
  if (tone === "running") {
    return styles.agentActivityRunning;
  }
  if (tone === "approval") {
    return styles.agentActivityApproval;
  }
  if (tone === "error") {
    return styles.agentActivityError;
  }
  if (tone === "completed") {
    return styles.agentActivityCompleted;
  }
  return "";
}

function teamRouteFor(team: Team) {
  return `/teams?team=${encodeURIComponent(team.teamId)}`;
}

export function AgentConversationDirectory({
  activeAgentId,
  activeSessionId = null,
  activeGroupRoomId = "",
  agents,
  avatarInitials,
  filterText,
  formatTime,
  lang,
  resolveModelLabel,
  runtimeRunningSessionIds = [],
  sessions,
  sessionIdsNeedingApproval = [],
  statusLabel,
  teams = [],
  onContextMenu,
  onOpenAgent,
  onOpenGroupRoom,
}: AgentConversationDirectoryProps) {
  const partition = useMemo(
    () => buildAgentDirectoryPartition({ agents, teams, sessions, filterText }),
    [agents, teams, sessions, filterText],
  );
  const { conversationAgents, specialAgents, teamBlocks, listedAgentIds } = partition;

  const [collapsedSections, setCollapsedSections] = useState<Record<string, boolean>>({
    ...DEFAULT_COLLAPSED_DIRECTORY_SECTIONS,
  });
  const approvalSessionIds = new Set(
    sessionIdsNeedingApproval.map((id) => String(id || "").trim()).filter(Boolean),
  );
  const runtimeSessionIds = new Set(
    runtimeRunningSessionIds.map((id) => String(id || "").trim()).filter(Boolean),
  );
  const sessionCountByAgentId = new Map<string, number>();
  const sessionIdsByAgentId = new Map<string, Set<string>>();
  const sessionsByAgentId = new Map<string, SessionSummary[]>();
  const latestSessionByAgentId = new Map<string, SessionSummary>();
  for (const session of sessions) {
    const agentId = String(session.agentId || "").trim();
    if (!agentId) {
      continue;
    }
    sessionCountByAgentId.set(agentId, (sessionCountByAgentId.get(agentId) || 0) + 1);
    const sessionIds = sessionIdsByAgentId.get(agentId) || new Set<string>();
    const sessionId = String(session.id || "").trim();
    if (sessionId) {
      sessionIds.add(sessionId);
    }
    sessionIdsByAgentId.set(agentId, sessionIds);
    const agentSessions = sessionsByAgentId.get(agentId) || [];
    agentSessions.push(session);
    sessionsByAgentId.set(agentId, agentSessions);
    const previous = latestSessionByAgentId.get(agentId);
    if (!previous || String(previous.updatedAt || previous.lastActive || "") < String(session.updatedAt || session.lastActive || "")) {
      latestSessionByAgentId.set(agentId, session);
    }
  }

  const isSectionExpanded = (sectionKey: string, defaultCollapsed = false) => {
    if (Object.prototype.hasOwnProperty.call(collapsedSections, sectionKey)) {
      return !collapsedSections[sectionKey];
    }
    return !defaultCollapsed;
  };

  const toggleSection = (sectionKey: string, defaultCollapsed = false) => {
    setCollapsedSections((current) => {
      const currentlyCollapsed = Object.prototype.hasOwnProperty.call(current, sectionKey)
        ? Boolean(current[sectionKey])
        : defaultCollapsed;
      return { ...current, [sectionKey]: !currentlyCollapsed };
    });
  };

  const renderAgent = (agent: AgentInstance) => {
    const agentId = String(agent.agentId || "").trim();
    const latestSession = latestSessionByAgentId.get(agentId);
    const display = agentDisplayInfo(agent, lang, { resolveModelLabel });
    const sessionCount = agentDirectorySessionCount(
      agent,
      sessionCountByAgentId.get(agentId) || 0,
      sessionIdsByAgentId.get(agentId) || new Set<string>(),
    );
    const active = agentId === activeAgentId;
    const avatarUrl = String(agent.avatarImageUrl || "").trim();
    const agentSessions = sessionsByAgentId.get(agentId) || [];
    const sessionTones = agentSessions.map((session) =>
      resolveSessionActivityTone(session, {
        needsApproval: approvalSessionIds.has(String(session.id || "").trim()),
        isRuntimeRunning: runtimeSessionIds.has(String(session.id || "").trim()),
        isActive: String(session.id || "").trim() === String(activeSessionId || "").trim(),
      }),
    );
    const activityTone = resolveAgentActivityTone(sessionTones);
    const activityLabel = sessionActivityLabel(activityTone, lang);
    const activityClassName = agentActivityClass(activityTone);
    return (
      <VButton
        key={agentId}
        type="button"
        variant="ghost"
        contentLayout="plain"
        className={[styles.agentRow, active ? styles.agentRowActive : ""].filter(Boolean).join(" ")}
        aria-current={active ? "page" : undefined}
        onContextMenu={(event) => onContextMenu(event, agent, latestSession ?? null)}
        onPress={() => onOpenAgent(agent, latestSession ?? null)}
      >
        <span className={styles.agentAvatar} aria-hidden="true">
          {avatarUrl ? (
            <img
              className={styles.agentAvatarImage}
              src={avatarUrl}
              alt=""
              onError={(event) => {
                const image = event.currentTarget;
                image.style.display = "none";
                const parent = image.parentElement;
                if (parent && !parent.dataset.avatarFallback) {
                  parent.dataset.avatarFallback = "1";
                  parent.textContent = avatarInitials(agent.agentCode, display.name, agentId);
                }
              }}
            />
          ) : (
            avatarInitials(agent.agentCode, display.name, agentId)
          )}
        </span>
        <span className={styles.agentCopy}>
          <span className={styles.agentTitleRow}>
            <span className={styles.agentTitle}>{display.name}</span>
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
        <span
          className={styles.agentStatusSlot}
          data-agent-status-slot
          aria-label={activityTone !== "none" ? activityLabel : undefined}
          title={activityTone !== "none" ? activityLabel : undefined}
          aria-hidden={activityTone === "none" ? true : undefined}
        >
          {activityTone !== "none" ? (
            <span className={[styles.agentActivity, activityClassName].filter(Boolean).join(" ")}>
              {activityTone === "running" || activityTone === "approval" ? (
                <LoaderCircle size={11} aria-hidden="true" className={styles.agentActivitySpinner} />
              ) : null}
            </span>
          ) : null}
        </span>
      </VButton>
    );
  };

  const renderAgentSection = (section: AgentDirectorySection, sectionAgents: AgentInstance[]) => {
    if (!sectionAgents.length) {
      return null;
    }
    const label = section === "conversation"
      ? (lang === "zh" ? "会话 Agent" : "Conversation Agents")
      : (lang === "zh" ? "特殊 Agent" : "Special Agents");
    const expanded = isSectionExpanded(section, DEFAULT_COLLAPSED_DIRECTORY_SECTIONS[section]);
    return (
      <ConversationIndexSection
        className={styles.agentSection}
        count={sectionAgents.length}
        expanded={expanded}
        label={label}
        onToggle={() => toggleSection(section, DEFAULT_COLLAPSED_DIRECTORY_SECTIONS[section])}
      >
        <div className={styles.agentDirectoryList}>{sectionAgents.map(renderAgent)}</div>
      </ConversationIndexSection>
    );
  };

  const renderTeamBlock = (block: (typeof teamBlocks)[number]) => {
    const teamId = String(block.team.teamId || "").trim();
    const sectionKey = `team:${teamId}`;
    // Team blocks default collapsed when there are many teams.
    const defaultCollapsed = teamBlocks.length > 3;
    const expanded = isSectionExpanded(sectionKey, defaultCollapsed);
    const count = (block.roomId ? 1 : 0) + block.agents.length;
    return (
      <ConversationIndexSection
        key={sectionKey}
        className={styles.agentSection}
        count={count}
        expanded={expanded}
        label={block.team.name || teamId}
        onToggle={() => toggleSection(sectionKey, defaultCollapsed)}
      >
        <div className={styles.agentDirectoryList}>
          <TeamConversationIndexItem
            active={Boolean(block.roomId && activeGroupRoomId === block.roomId)}
            displayTitle={lang === "zh" ? "团队群聊" : "Team chat"}
            lang={lang}
            roomId={block.roomId}
            team={block.team}
            teamRoute={teamRouteFor(block.team)}
            statusLabel={statusLabel}
            onOpen={(roomId) => onOpenGroupRoom?.(roomId)}
          />
          {block.agents.map(renderAgent)}
        </div>
      </ConversationIndexSection>
    );
  };

  const hasContent = listedAgentIds.length > 0 || teamBlocks.length > 0;

  return (
    <nav className={styles.agentDirectory} aria-label={lang === "zh" ? "Agent 目录" : "Agent directory"}>
      <div className={styles.agentDirectoryHeader}>
        <span>{lang === "zh" ? "Agent" : "Agents"}</span>
        <span className={styles.agentDirectoryCount}>{listedAgentIds.length}</span>
      </div>
      {hasContent ? (
        <>
          {renderAgentSection("conversation", conversationAgents)}
          {teamBlocks.map(renderTeamBlock)}
          {renderAgentSection("special", specialAgents)}
        </>
      ) : (
        <p className={styles.agentEmpty}>
          {lang === "zh" ? "暂无可用 Agent。新建 Agent 后可在其下建立多个会话。" : "No available Agents. Create an Agent, then add sessions under it."}
        </p>
      )}
    </nav>
  );
}
