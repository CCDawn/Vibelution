import type { AgentInstance, ConversationSummary, SessionSummary, Team } from "../api/types";
import { agentArchiveProtected } from "./agentArchiveProtection";
import { agentDisplayInfo, type ModelLabelResolver } from "./agentDisplay";
import {
  buildConversationTeamLookup,
  isConfiguredConversationIndexTeam,
  type ConversationIndexTeam,
} from "./conversationIndexModel";

/**
 * Left-rail Agent directory partitioning.
 *
 * - conversation: pure chat agents with no team membership and no archive protection
 * - team blocks: every non-archived team with members or linked room
 *   (includes research + evolution system teams so their chats leave 未归属)
 * - special: non-conversation agents with no team membership, including
 *   unassigned archive-protected research-org / system roles
 */

export type AgentDirectoryBucket = "conversation" | "team" | "special";

export type AgentDirectoryTeamBlock = {
  team: ConversationIndexTeam;
  agents: AgentInstance[];
  roomId: string;
};

export type AgentDirectoryPartition = {
  conversationAgents: AgentInstance[];
  specialAgents: AgentInstance[];
  teamBlocks: AgentDirectoryTeamBlock[];
  /** All agents shown somewhere in the directory (deduped). */
  listedAgentIds: string[];
};

function storedConversationIndexKind(agent: AgentInstance) {
  return String(
    agent.conversationIndexKind
    || agent.metadata?.conversationIndexKind
    || "",
  ).trim();
}

export function isEligibleDirectoryAgent(agent: AgentInstance) {
  const metadata = agent.metadata ?? {};
  return (
    String(agent.kind || "").trim() === "persistent"
    && String(agent.status || "").trim() !== "archived"
    && metadata.virtualHumanCompanion !== true
  );
}

/** Pure conversation entry: chat mode without a specialized or protected role. */
export function isConversationDirectoryAgent(agent: AgentInstance) {
  if (agentArchiveProtected(agent)) {
    return false;
  }
  const primaryMode = String(agent.primaryMode || "").trim();
  const roleKey = String(agent.roleKey || "").trim();
  return primaryMode === "chat" && !roleKey;
}

/**
 * Flat-directory visibility (legacy + non-team_agent).
 * Team members are listed under team blocks even when kind is team_agent.
 */
export function isVisibleFlatDirectoryAgent(agent: AgentInstance) {
  return isEligibleDirectoryAgent(agent) && storedConversationIndexKind(agent) !== "team_agent";
}

export function agentDirectoryBucket(
  agent: AgentInstance,
  assignedTeamAgentIds: ReadonlySet<string>,
): AgentDirectoryBucket {
  const agentId = String(agent.agentId || "").trim();
  if (agentId && assignedTeamAgentIds.has(agentId)) {
    return "team";
  }
  return isConversationDirectoryAgent(agent) ? "conversation" : "special";
}

function isAgentTextMatch(agent: AgentInstance, filterText: string, lang: "zh" | "en", resolveModelLabel?: ModelLabelResolver) {
  const query = String(filterText || "").trim().toLocaleLowerCase();
  if (!query) {
    return true;
  }
  const display = agentDisplayInfo(agent, lang, { resolveModelLabel });
  return [display.name, display.functionLabel, display.modelLabel, agent.agentCode, agent.roleKey, agent.primaryMode]
    .join(" ")
    .toLocaleLowerCase()
    .includes(query);
}

function isTeamTextMatch(team: ConversationIndexTeam, filterText: string) {
  const query = String(filterText || "").trim().toLocaleLowerCase();
  if (!query) {
    return true;
  }
  return [
    team.name,
    team.purpose,
    team.teamKind,
    team.teamCategory,
    team.linkedChatRoom?.title ?? "",
    ...(team.members ?? []).flatMap((member) => [member.agentName, member.agentCode, member.role]),
  ].some((value) => String(value ?? "").toLowerCase().includes(query));
}

/**
 * Directory team list: keep non-archived teams (including self/supervised evolution).
 * Conversation-index "discussion only" filtering must not hide system teams here.
 */
export function normalizeDirectoryTeams(teams: Team[]): ConversationIndexTeam[] {
  const byId = new Map<string, ConversationIndexTeam>();
  for (const team of teams ?? []) {
    const status = String(team.status ?? "").trim().toLowerCase();
    if (status === "archived") {
      continue;
    }
    const teamId = String(team.teamId ?? "").trim();
    if (!teamId || byId.has(teamId)) {
      continue;
    }
    const roomId = String(team.linkedChatRoomId || team.linkedChatRoom?.roomId || "").trim();
    const hasMembers = isConfiguredConversationIndexTeam(team);
    if (!hasMembers && !roomId) {
      continue;
    }
    byId.set(teamId, {
      ...team,
      linkedChatRoomId: roomId || team.linkedChatRoomId,
    });
  }
  return [...byId.values()];
}

/**
 * Build primary-team assignment: first team that lists the agent wins
 * (same first-wins rule as buildConversationTeamLookup).
 */
export function buildAgentPrimaryTeamIdMap(teams: ConversationIndexTeam[]): Map<string, string> {
  const lookup = buildConversationTeamLookup(teams);
  const map = new Map<string, string>();
  lookup.byAgentId.forEach((team, agentId) => {
    const teamId = String(team.teamId || "").trim();
    if (agentId && teamId) {
      map.set(agentId, teamId);
    }
  });
  return map;
}

/**
 * Left-rail conversation/special order is independent of rename and other
 * display-name PATCH bumps to `updatedAt`. Newest created Agent stays first.
 */
export function compareAgentDirectoryStableOrder(
  left: AgentInstance,
  right: AgentInstance,
): number {
  const leftCreated = String(left.createdAt || "").trim();
  const rightCreated = String(right.createdAt || "").trim();
  if (leftCreated !== rightCreated) {
    return rightCreated.localeCompare(leftCreated);
  }
  return String(left.agentId || "").localeCompare(String(right.agentId || ""));
}

/** Room ids owned by any directory team (used to keep 未归属 empty when links are valid). */
export function directoryLinkedRoomIds(teams: readonly Team[] | ConversationIndexTeam[]): Set<string> {
  const ids = new Set<string>();
  for (const team of teams ?? []) {
    const roomId = String(
      (team as Team).linkedChatRoomId
      || (team as Team).linkedChatRoom?.roomId
      || "",
    ).trim();
    if (roomId) {
      ids.add(roomId);
    }
  }
  return ids;
}

/** Teams rendered as team blocks in the Agent directory (members or a linked room). */
export function isDirectoryTeamBlockTeam(team: Team): boolean {
  return (
    isConfiguredConversationIndexTeam(team)
    || Boolean(String(team.linkedChatRoomId || team.linkedChatRoom?.roomId || "").trim())
  );
}

/** Team ids owned by directory team blocks; the rail dedupes tree team groups against this set. */
export function directoryTeamBlockIds(teams: readonly Team[]): Set<string> {
  const teamIds = new Set<string>();
  for (const team of normalizeDirectoryTeams([...teams])) {
    const teamId = String(team.teamId || "").trim();
    if (teamId && isDirectoryTeamBlockTeam(team)) {
      teamIds.add(teamId);
    }
  }
  return teamIds;
}

export function buildAgentDirectoryPartition(options: {
  agents: AgentInstance[];
  teams: Team[];
  /** Optional; kept for experiment-session hooks / future filters. */
  sessions?: SessionSummary[];
  filterText?: string;
  lang?: "zh" | "en";
  resolveModelLabel?: ModelLabelResolver;
}): AgentDirectoryPartition {
  void options.sessions;
  const filterText = String(options.filterText || "").trim();
  const directoryTeams = normalizeDirectoryTeams(options.teams ?? []);
  // Prefer teams with members; still keep room-only teams so chats leave 未归属.
  const configuredTeams = directoryTeams.filter(isDirectoryTeamBlockTeam);
  const primaryTeamByAgentId = buildAgentPrimaryTeamIdMap(directoryTeams);

  const agentsById = new Map<string, AgentInstance>();
  for (const agent of options.agents ?? []) {
    if (!isEligibleDirectoryAgent(agent)) {
      continue;
    }
    const agentId = String(agent.agentId || "").trim();
    if (agentId && !agentsById.has(agentId)) {
      agentsById.set(agentId, agent);
    }
  }

  const assignedAgentIds = new Set<string>();
  const teamBlocks: AgentDirectoryTeamBlock[] = [];

  for (const team of configuredTeams) {
    const teamId = String(team.teamId || "").trim();
    if (!teamId) {
      continue;
    }
    const roomId = String(team.linkedChatRoomId || team.linkedChatRoom?.roomId || "").trim();
    const seenInTeam = new Set<string>();
    const memberAgents: AgentInstance[] = [];

    for (const member of team.members ?? []) {
      const agentId = String(member.agentId || "").trim();
      if (!agentId || seenInTeam.has(agentId)) {
        continue;
      }
      // Primary team only: skip if this agent already belongs to an earlier team.
      if (primaryTeamByAgentId.get(agentId) !== teamId) {
        continue;
      }
      const agent = agentsById.get(agentId);
      if (!agent) {
        continue;
      }
      seenInTeam.add(agentId);
      assignedAgentIds.add(agentId);
      if (isAgentTextMatch(agent, filterText, options.lang ?? "zh", options.resolveModelLabel) || isTeamTextMatch(team, filterText)) {
        memberAgents.push(agent);
      }
    }

    // Also attach agents whose primary team is this team but missing from members list
    // (lookup already first-wins from members; this covers identity edge cases only when
    // primaryTeam map was populated from this team's members — no extra agents expected).

    const teamMatchesFilter = !filterText || isTeamTextMatch(team, filterText) || memberAgents.length > 0;
    if (!teamMatchesFilter) {
      continue;
    }
    // When filtering agents only, still show team if any member matched above.
    if (filterText && memberAgents.length === 0 && !isTeamTextMatch(team, filterText)) {
      continue;
    }

    teamBlocks.push({
      team,
      agents: memberAgents,
      roomId,
    });
  }

  const conversationAgents: AgentInstance[] = [];
  const specialAgents: AgentInstance[] = [];

  for (const agent of agentsById.values()) {
    const agentId = String(agent.agentId || "").trim();
    if (assignedAgentIds.has(agentId)) {
      continue;
    }
    if (!isAgentTextMatch(agent, filterText, options.lang ?? "zh", options.resolveModelLabel)) {
      continue;
    }
    // Flat visibility: team_agent without membership stays out of conversation/special
    // unless it is a non-team_agent special (or conversation).
    if (storedConversationIndexKind(agent) === "team_agent") {
      // Orphan team_agent: surface under special so it is still reachable.
      specialAgents.push(agent);
      continue;
    }
    if (isConversationDirectoryAgent(agent)) {
      conversationAgents.push(agent);
    } else {
      specialAgents.push(agent);
    }
  }

  conversationAgents.sort(compareAgentDirectoryStableOrder);
  specialAgents.sort(compareAgentDirectoryStableOrder);

  const listedAgentIds = [
    ...conversationAgents.map((agent) => String(agent.agentId || "").trim()),
    ...specialAgents.map((agent) => String(agent.agentId || "").trim()),
    ...teamBlocks.flatMap((block) => block.agents.map((agent) => String(agent.agentId || "").trim())),
  ].filter(Boolean);

  return {
    conversationAgents,
    specialAgents,
    teamBlocks,
    listedAgentIds: [...new Set(listedAgentIds)],
  };
}

export type AgentDirectoryTeamRoomHistoryGroup = {
  key: string;
  label: string;
  items: ConversationSummary[];
};

const TEAM_ROOM_HISTORY_TOPIC_PATTERN = /(^|[^A-Za-z0-9])sci-(\d+)(?=[^0-9]|$)/i;

function conversationUpdatedAtTimestamp(conversation: Pick<ConversationSummary, "updatedAt">): number {
  const parsedTimestamp = Date.parse(String(conversation.updatedAt || "").trim());
  return Number.isFinite(parsedTimestamp) ? parsedTimestamp : 0;
}

/**
 * Group a team's extra group rooms for the directory history fold.
 * Rooms are keyed by their `SCI-xxx` topic when present, otherwise fall into
 * a single trailing "other" group; both levels sort by most recent activity.
 */
export function buildAgentDirectoryTeamRoomHistoryGroups(
  rooms: readonly ConversationSummary[],
  options: { linkedRoomId?: string; otherLabel?: string } = {},
): AgentDirectoryTeamRoomHistoryGroup[] {
  const linkedRoomId = String(options.linkedRoomId || "").trim();
  const groups = new Map<string, AgentDirectoryTeamRoomHistoryGroup>();
  for (const room of rooms) {
    const roomId = String(room.roomId || room.conversationId || "").trim();
    if (!roomId || (linkedRoomId && roomId === linkedRoomId)) {
      continue;
    }
    const topicMatch = String(room.title || "").match(TEAM_ROOM_HISTORY_TOPIC_PATTERN);
    const topic = topicMatch ? `SCI-${topicMatch[2]}` : "";
    const groupKey = topic || "__other__";
    const group = groups.get(groupKey) ?? {
      key: groupKey,
      label: topic || String(options.otherLabel || ""),
      items: [],
    };
    group.items.push(room);
    groups.set(groupKey, group);
  }
  const ordered = [...groups.values()];
  for (const group of ordered) {
    group.items.sort(
      (left, right) => conversationUpdatedAtTimestamp(right) - conversationUpdatedAtTimestamp(left),
    );
  }
  ordered.sort((left, right) => {
    if (left.key === "__other__") return right.key === "__other__" ? 0 : 1;
    if (right.key === "__other__") return -1;
    const leftLatest = left.items[0] ? conversationUpdatedAtTimestamp(left.items[0]) : 0;
    const rightLatest = right.items[0] ? conversationUpdatedAtTimestamp(right.items[0]) : 0;
    if (leftLatest !== rightLatest) return rightLatest - leftLatest;
    return left.key.localeCompare(right.key);
  });
  return ordered;
}

const DIRECTORY_COLLAPSE_STORAGE_KEY = "vibelution.agent-directory.collapsed.v1";

export function readDirectoryCollapsedSections(): Record<string, boolean> {
  try {
    const value: unknown = JSON.parse(globalThis.localStorage?.getItem(DIRECTORY_COLLAPSE_STORAGE_KEY) || "{}");
    if (!value || typeof value !== "object" || Array.isArray(value)) return {};
    return Object.fromEntries(Object.entries(value).filter(([, collapsed]) => typeof collapsed === "boolean"));
  } catch {
    return {};
  }
}

export function writeDirectoryCollapsedSections(sections: Record<string, boolean>) {
  try {
    globalThis.localStorage?.setItem(DIRECTORY_COLLAPSE_STORAGE_KEY, JSON.stringify(sections));
  } catch {
    // A storage restriction must not prevent the user from expanding a group.
  }
}

/** @deprecated Prefer agentDirectoryBucket + buildAgentDirectoryPartition. */
export function agentDirectorySection(agent: AgentInstance): "conversation" | "special" {
  return isConversationDirectoryAgent(agent) ? "conversation" : "special";
}
