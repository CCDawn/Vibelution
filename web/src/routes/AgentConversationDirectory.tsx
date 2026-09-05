import { LoaderCircle } from "lucide-react";
import { useEffect, useMemo, useState, type MouseEvent as ReactMouseEvent } from "react";

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
  readDirectoryCollapsedSections,
  writeDirectoryCollapsedSections,
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
import { teamWorkspaceRoute } from "./teams/researchWorkspaceModel";

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
  special: true,
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

function sessionRecencyTimestamp(session: Pick<SessionSummary, "updatedAt" | "lastActive">): number {
  const rawTimestamp = String(session.updatedAt || session.lastActive || "").trim();
  if (!rawTimestamp) {
    return Number.NEGATIVE_INFINITY;
  }
  const parsedTimestamp = Date.parse(rawTimestamp);
  return Number.isFinite(parsedTimestamp) ? parsedTimestamp : Number.NEGATIVE_INFINITY;
}

export function isSessionMoreRecent(
  candidate: Pick<SessionSummary, "id" | "updatedAt" | "lastActive">,
  previous: Pick<SessionSummary, "id" | "updatedAt" | "lastActive">,
  activeSessionId = "",
): boolean {
  const normalizedActiveSessionId = activeSessionId.trim();
  if (normalizedActiveSessionId) {
    if (candidate.id === normalizedActiveSessionId && previous.id !== normalizedActiveSessionId) {
      return true;
    }
    if (previous.id === normalizedActiveSessionId) {
      return false;
    }
  }
  const candidateTimestamp = sessionRecencyTimestamp(candidate);
  const previousTimestamp = sessionRecencyTimestamp(previous);
  if (candidateTimestamp !== previousTimestamp) {
    return candidateTimestamp > previousTimestamp;
  }
  return String(candidate.updatedAt || candidate.lastActive || "")
    > String(previous.updatedAt || previous.lastActive || "");
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
  return teamWorkspaceRoute(team.teamId);
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
    () => buildAgentDirectoryPartition({ agents, teams, sessions, filterText, lang, resolveModelLabel }),
    [agents, teams, sessions, filterText, lang, resolveModelLabel],
  );
  const { conversationAgents, specialAgents, teamBlocks, listedAgentIds } = partition;

  const [collapsedSections, setCollapsedSections] = useState<Record<string, boolean>>(() => ({
    ...DEFAULT_COLLAPSED_DIRECTORY_SECTIONS,
    ...readDirectoryCollapsedSections(),
  }));
  const activeSectionKey = useMemo(() => {
    const all = buildAgentDirectoryPartition({ agents, teams });
    const team = all.teamBlocks.find((block) => (
      Boolean(activeGroupRoomId && block.roomId === activeGroupRoomId)
      || block.agents.some((agent) => agent.agentId === activeAgentId)
    ));
    if (team) return `team:${team.team.teamId}`;
    if (all.specialAgents.some((agent) => agent.agentId === activeAgentId)) return "special";
    return all.conversationAgents.some((agent) => agent.agentId === activeAgentId) ? "conversation" : "";
  }, [agents, teams, activeAgentId, activeGroupRoomId]);
  useEffect(() => {
    if (activeSectionKey) {
      setCollapsedSections((current) => current[activeSectionKey] === false ? current : { ...current, [activeSectionKey]: false });
    }
  }, [activeSectionKey]);
  useEffect(() => writeDirectoryCollapsedSections(collapsedSections), [collapsedSections]);
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
    if (!previous || isSessionMoreRecent(session, previous, String(activeSessionId || ""))) {
      latestSessionByAgentId.set(agentId, session);
    }
  }

  const isSectionExpanded = (sectionKey: string, defaultCollapsed = false) => {
    if (filterText.trim()) return true;
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

  const activityByAgentId = new Map<string, SessionActivityTone>();
  for (const agent of agents) {
    const tones = (sessionsByAgentId.get(agent.agentId) || []).map((session) => resolveSessionActivityTone(session, {
      needsApproval: approvalSessionIds.has(session.id),
      isRuntimeRunning: runtimeSessionIds.has(session.id),
      isActive: session.id === activeSessionId,
    }));
    activityByAgentId.set(agent.agentId, resolveAgentActivityTone(tones));
  }
  const renderActivity = (tone: SessionActivityTone) => tone === "none" ? null : (
    <span className={[styles.agentActivity, agentActivityClass(tone)].filter(Boolean).join(" ")} aria-label={sessionActivityLabel(tone, lang)} title={sessionActivityLabel(tone, lang)}>
      {tone === "running" || tone === "approval" ? <LoaderCircle size={11} aria-hidden="true" className={styles.agentActivitySpinner} /> : null}
    </span>
  );
  const sectionActivity = (sectionAgents: AgentInstance[], expanded: boolean) => expanded ? undefined : renderActivity(
    resolveAgentActivityTone(sectionAgents.map((agent) => activityByAgentId.get(agent.agentId) || "none")),
  );

  const renderAgent = (agent: AgentInstance, showRole: boolean) => {
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
    const activityTone = activityByAgentId.get(agentId) || "none";
    const activityLabel = sessionActivityLabel(activityTone, lang);
    const modelLabel = display.modelLabel || (lang === "zh" ? "未配置模型" : "No model");
    const subtitle = showRole && display.functionLabel !== display.name ? display.functionLabel : modelLabel;
    const sessionCountLabel = lang === "zh" ? `${sessionCount} 个会话` : `${sessionCount} sessions`;
    const details = [display.name, display.functionLabel, modelLabel, sessionCountLabel,
      latestSession ? formatTime(latestSession.updatedAt || latestSession.lastActive) : "",
      activityTone !== "none" ? activityLabel : "",
    ].filter(Boolean).filter((value, index, values) => values.indexOf(value) === index).join(" · ");
    return (
      <VButton
        key={agentId}
        type="button"
        variant="ghost"
        contentLayout="plain"
        className={[styles.agentRow, active ? styles.agentRowActive : ""].filter(Boolean).join(" ")}
        data-selected={active ? "true" : undefined}
        aria-current={active ? "page" : undefined}
        tooltip={details}
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
            <span className={styles.agentMetaItem}>{subtitle}</span>
          </span>
        </span>
        <span
          className={styles.agentStatusSlot}
          data-agent-status-slot
          aria-label={activityTone !== "none" ? activityLabel : undefined}
          title={activityTone !== "none" ? activityLabel : undefined}
          aria-hidden={activityTone === "none" && sessionCount <= 1 ? true : undefined}
        >
          {sessionCount > 1 ? <span className={styles.agentMetaCount} aria-label={sessionCountLabel}>{sessionCount}</span> : null}
          {renderActivity(activityTone)}
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
        countLabel={lang === "zh" ? `${sectionAgents.length} 个 Agent` : `${sectionAgents.length} Agents`}
        activity={sectionActivity(sectionAgents, expanded)}
        expanded={expanded}
        label={label}
        onToggle={() => toggleSection(section, DEFAULT_COLLAPSED_DIRECTORY_SECTIONS[section])}
      >
        <div className={styles.agentDirectoryList}>{sectionAgents.map((agent) => renderAgent(agent, section === "special"))}</div>
      </ConversationIndexSection>
    );
  };

  const renderTeamBlock = (block: (typeof teamBlocks)[number]) => {
    const teamId = String(block.team.teamId || "").trim();
    const sectionKey = `team:${teamId}`;
    const defaultCollapsed = true;
    const expanded = isSectionExpanded(sectionKey, defaultCollapsed);
    const count = block.agents.length;
    return (
      <ConversationIndexSection
        key={sectionKey}
        className={styles.agentSection}
        count={count}
        countLabel={lang === "zh" ? `${count} 个 Agent` : `${count} Agents`}
        activity={sectionActivity(block.agents, expanded)}
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
          {block.agents.map((agent) => renderAgent(agent, true))}
        </div>
      </ConversationIndexSection>
    );
  };

  const hasContent = listedAgentIds.length > 0 || teamBlocks.length > 0;

  return (
    <nav className={styles.agentDirectory} aria-label={lang === "zh" ? "Agent 目录" : "Agent directory"}>
      {hasContent ? (
        <>
          {renderAgentSection("conversation", conversationAgents)}
          {teamBlocks.map(renderTeamBlock)}
          {renderAgentSection("special", specialAgents)}
        </>
      ) : (
        <p className={styles.agentEmpty}>
          {filterText.trim()
            ? (lang === "zh" ? "没有匹配的 Agent 或团队" : "No matching Agents or teams")
            : (lang === "zh" ? "暂无可用 Agent。新建 Agent 后可在其下建立多个会话。" : "No available Agents. Create an Agent, then add sessions under it.")}
        </p>
      )}
    </nav>
  );
}
