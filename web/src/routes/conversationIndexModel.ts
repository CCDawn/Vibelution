import { useMemo } from "react";

import type {
  AgentInstance,
  ConversationSummary,
  ProjectionEditContract,
  SessionSummary,
  SourceAuthorityRef,
  Team,
} from "../api/types";
import { isChildSession, sessionListTitle } from "./DirectSessionIndexItem";

export type ConversationIndexGroupKey =
  | "user"
  | "group"
  | "personalAgent"
  | "research"
  | "selfEvolution"
  | "supervisedEvolution"
  | "teams"
  | "setupTeams"
  | "standaloneGroups"
  | "other"
  | "invalid";

export type ConversationIndexDynamicGroupKey = ConversationIndexGroupKey | `team:${string}`;

export type ConversationIndexGroup = {
  groupKey: ConversationIndexDynamicGroupKey;
  label: string;
  items: ConversationSummary[];
  teamId?: string;
  groupKind?: "default" | "team";
};

export type ConversationIndexTeam = Team & {
  conversationIndexDuplicateCount?: number;
  conversationIndexHiddenTeamIds?: string[];
  conversationIndexSetupReason?: "empty_members";
};

const USER_VISIBLE_CONVERSATION_INDEX_VISIBILITY = "user_visible";
const TEAM_PRIVATE_CONVERSATION_INDEX_VISIBILITY = "team_private";
const HIDDEN_CONVERSATION_INDEX_VISIBILITY = "hidden";
const CONVERSATION_INDEX_KIND_USER_CHAT = "user_chat";
const CONVERSATION_INDEX_KIND_PERSONAL_AGENT = "personal_agent";
const CONVERSATION_INDEX_KIND_TEAM_AGENT = "team_agent";
const CONVERSATION_INDEX_KIND_SYSTEM_ENTRY = "system_entry";
const CONVERSATION_INDEX_KIND_HIDDEN = "hidden";
const CONVERSATION_INDEX_KIND_INVALID = "invalid";
const CONVERSATION_INDEX_KINDS = new Set([
  CONVERSATION_INDEX_KIND_USER_CHAT,
  CONVERSATION_INDEX_KIND_PERSONAL_AGENT,
  CONVERSATION_INDEX_KIND_TEAM_AGENT,
  CONVERSATION_INDEX_KIND_SYSTEM_ENTRY,
  CONVERSATION_INDEX_KIND_HIDDEN,
  CONVERSATION_INDEX_KIND_INVALID,
]);

export const DEFAULT_COLLAPSED_CONVERSATION_GROUPS: Record<ConversationIndexGroupKey, boolean> = {
  user: false,
  group: false,
  personalAgent: false,
  research: false,
  selfEvolution: false,
  supervisedEvolution: false,
  teams: false,
  setupTeams: true,
  standaloneGroups: true,
  other: false,
  invalid: false,
};

export const CONVERSATION_GROUP_ORDER: ConversationIndexGroupKey[] = [
  "user",
  "group",
  "personalAgent",
  "research",
  "selfEvolution",
  "supervisedEvolution",
  "other",
  "invalid",
];

type TeamAwareConversationSummary = ConversationSummary & {
  teamId?: string;
  teamName?: string;
};

type ConversationTeamLookup = {
  byAgentCode: Map<string, ConversationIndexTeam>;
  byAgentId: Map<string, ConversationIndexTeam>;
  byTeamId: Map<string, ConversationIndexTeam>;
  byTeamName: Map<string, ConversationIndexTeam>;
};

const NON_DISCUSSION_TEAM_IDS = new Set(["self-evolution-team", "supervised-evolution-team"]);
const NON_DISCUSSION_TEAM_KINDS = new Set(["self_evolution", "supervised_evolution"]);
const NON_DISCUSSION_TEAM_SOURCES = new Set(["self_evolution", "supervised_evolution"]);
const SOURCE_AUTHORITY_VERSION = 1;
const ALLOWED_PROJECTION_ACTIONS = ["view", "link", "refresh", "repair"];

export function isDiscussionTeam(team: Team | undefined | null) {
  if (!team) {
    return false;
  }
  const teamId = String(team.teamId ?? "").trim();
  const teamKind = String(team.teamKind ?? "").trim();
  const teamSource = String(team.teamSource ?? "").trim();
  const status = String(team.status ?? "").trim().toLowerCase();
  if (status === "archived") {
    return false;
  }
  return !(
    NON_DISCUSSION_TEAM_IDS.has(teamId)
    || NON_DISCUSSION_TEAM_KINDS.has(teamKind)
    || NON_DISCUSSION_TEAM_SOURCES.has(teamSource)
  );
}

export function conversationIndexTeamMemberCount(team: Pick<Team, "members" | "memberCount"> | undefined | null) {
  if (!team) {
    return 0;
  }
  return Math.max(Number(team.memberCount) || 0, team.members?.length || 0);
}

export function isConfiguredConversationIndexTeam(team: Pick<Team, "members" | "memberCount"> | undefined | null) {
  return conversationIndexTeamMemberCount(team) > 0;
}

function normalizedTeamName(team: Team) {
  return String(team.name ?? "").trim().toLowerCase();
}

function conversationTeamDedupeKey(team: Team) {
  const name = normalizedTeamName(team) || String(team.teamId ?? "").trim().toLowerCase();
  const kind = String(team.teamKind ?? "").trim().toLowerCase();
  const source = String(team.teamSource ?? "manual").trim().toLowerCase() || "manual";
  const templateId = String(team.teamTemplateId ?? "").trim().toLowerCase();
  return [source, kind, templateId, name].join("|");
}

function conversationTeamScore(team: Team, index: number) {
  const memberScore = isConfiguredConversationIndexTeam(team) ? 1000 : 0;
  const roomScore = String(team.linkedChatRoomId ?? "").trim() ? 100 : 0;
  const sourceScore = String(team.teamSource ?? "").trim() && team.teamSource !== "manual" ? 10 : 0;
  return memberScore + roomScore + sourceScore - index / 1000;
}

export function conversationTeamGroupKey(teamId: string): `team:${string}` {
  return `team:${teamId}`;
}

export function normalizeConversationIndexTeams(teams: Team[]): ConversationIndexTeam[] {
  const buckets = new Map<string, {
    representative: ConversationIndexTeam;
    representativeIndex: number;
    score: number;
    teamIds: string[];
  }>();

  teams.forEach((team, index) => {
    if (!isDiscussionTeam(team)) {
      return;
    }
    const key = conversationTeamDedupeKey(team);
    const teamId = String(team.teamId ?? "").trim();
    const score = conversationTeamScore(team, index);
    const existing = buckets.get(key);
    if (!existing) {
      buckets.set(key, {
        representative: { ...team },
        representativeIndex: index,
        score,
        teamIds: teamId ? [teamId] : [],
      });
      return;
    }
    if (teamId) {
      existing.teamIds.push(teamId);
    }
    if (score > existing.score) {
      existing.representative = { ...team };
      existing.representativeIndex = index;
      existing.score = score;
    }
  });

  return [...buckets.values()]
    .sort((left, right) => left.representativeIndex - right.representativeIndex)
    .map((bucket) => {
      const representativeId = String(bucket.representative.teamId ?? "").trim();
      const hiddenTeamIds = bucket.teamIds.filter((teamId) => teamId && teamId !== representativeId);
      return {
        ...bucket.representative,
        conversationIndexDuplicateCount: bucket.teamIds.length,
        conversationIndexHiddenTeamIds: hiddenTeamIds,
        conversationIndexSetupReason: isConfiguredConversationIndexTeam(bucket.representative) ? undefined : "empty_members",
      };
    });
}

export function buildConversationTeamLookup(teams: ConversationIndexTeam[]): ConversationTeamLookup {
  const lookup: ConversationTeamLookup = {
    byAgentCode: new Map(),
    byAgentId: new Map(),
    byTeamId: new Map(),
    byTeamName: new Map(),
  };
  teams.forEach((team) => {
    const teamName = String(team.name ?? "").trim().toLowerCase();
    if (teamName && !lookup.byTeamName.has(teamName)) {
      lookup.byTeamName.set(teamName, team);
    }
    const teamIds = [
      String(team.teamId ?? "").trim(),
      ...(team.conversationIndexHiddenTeamIds ?? []).map((teamId) => String(teamId ?? "").trim()),
    ].filter(Boolean);
    teamIds.forEach((teamId) => lookup.byTeamId.set(teamId, team));
    (team.members ?? []).forEach((member) => {
      const agentId = String(member.agentId ?? "").trim();
      const agentCode = String(member.agentCode ?? "").trim().toLowerCase();
      if (agentId && !lookup.byAgentId.has(agentId)) {
        lookup.byAgentId.set(agentId, team);
      }
      if (agentCode && !lookup.byAgentCode.has(agentCode)) {
        lookup.byAgentCode.set(agentCode, team);
      }
    });
  });
  return lookup;
}

export function conversationTeamFor(
  conversation: ConversationSummary,
  lookup: ConversationTeamLookup,
): ConversationIndexTeam | undefined {
  if (conversation.type !== "direct_agent") {
    return undefined;
  }
  const teamAwareConversation = conversation as TeamAwareConversationSummary;
  const directTeamId = String(teamAwareConversation.teamId ?? "").trim();
  if (directTeamId) {
    const team = lookup.byTeamId.get(directTeamId);
    if (team) {
      return team;
    }
  }
  const directTeamName = String(teamAwareConversation.teamName ?? "").trim().toLowerCase();
  if (directTeamName) {
    const team = lookup.byTeamName.get(directTeamName);
    if (team) {
      return team;
    }
  }
  const agentId = String(conversation.agentId ?? "").trim();
  if (agentId) {
    const team = lookup.byAgentId.get(agentId);
    if (team) {
      return team;
    }
  }
  const agentCode = String(conversation.agentCode ?? "").trim().toLowerCase();
  if (agentCode) {
    return lookup.byAgentCode.get(agentCode);
  }
  return undefined;
}

function conversationTeamSearchValues(team: ConversationIndexTeam | undefined): string[] {
  if (!team) {
    return [];
  }
  return [
    team.teamId,
    team.name,
    team.purpose,
    team.status,
    team.teamKind,
    team.teamCategory,
    team.teamSource,
    team.teamTemplateId ?? "",
    team.linkedChatRoom?.title ?? "",
    ...(team.members ?? []).flatMap((member) => [member.agentName, member.agentCode, member.role, member.purpose]),
  ];
}

export function sessionToConversationSummary(session: SessionSummary): ConversationSummary {
  const sourceRef = session.sourceRef ?? makeSourceAuthorityRef("session", session.id);
  const projectionEdit = session.projectionEdit ?? makeProjectionEditContract(sourceRef);
  const agentSourceRef = session.agentSourceRef
    ?? (session.agentId ? makeSourceAuthorityRef("agent", session.agentId) : null);
  return {
    conversationId: session.id,
    type: "direct_agent",
    title: sessionListTitle(session),
    agentId: session.agentId,
    agentCode: session.agentCode,
    agentDisplayName: session.agentDisplayName,
    agentAvatarImagePath: session.agentAvatarImagePath,
    agentAvatarImageUrl: session.agentAvatarImageUrl,
    directSessionId: session.id,
    roomId: "",
    status: session.status,
    summary: session.taskSummary,
    updatedAt: session.updatedAt || session.lastActive,
    workspacePath: session.agentWorkspacePath || session.workspacePath || "",
    agentPrimaryMode: session.agentPrimaryMode,
    agentRoleKey: session.agentRoleKey,
    agentPromptTemplateId: session.agentPromptTemplateId,
    dialogueModelId: session.dialogueModelId,
    agentInboxPendingCount: session.agentInboxPendingCount,
    conversationIndexVisibility: session.conversationIndexVisibility,
    conversationIndexKind: session.conversationIndexKind,
    conversationIndexErrors: session.conversationIndexErrors ?? [],
    sourceRef,
    projectionEdit,
    agentSourceRef,
  };
}

function normalizeConversationIndexKind(value: unknown) {
  const kind = String(value ?? "").trim();
  return CONVERSATION_INDEX_KINDS.has(kind) ? kind : "";
}

function metadataString(agent: AgentInstance, key: string) {
  return String(agent.metadata?.[key] ?? "").trim();
}

function agentConversationIndexClassification(agent: AgentInstance) {
  const rawKind = String(agent.conversationIndexKind ?? agent.metadata?.conversationIndexKind ?? "").trim();
  const explicitKind = normalizeConversationIndexKind(rawKind);
  const errors: string[] = [];
  if (rawKind && !explicitKind) {
    errors.push("invalid_conversation_index_kind");
  }
  if (!explicitKind) {
    errors.push("missing_conversation_index_kind");
  }
  const createdBy = String(agent.createdBy ?? "").trim();
  if (!explicitKind && createdBy === "session_repair") {
    errors.push("session_repair_missing_conversation_index_kind");
  }
  const kind = explicitKind || CONVERSATION_INDEX_KIND_INVALID;
  if (kind === CONVERSATION_INDEX_KIND_TEAM_AGENT) {
    const hasTeamMarker = Boolean(
      metadataString(agent, "teamId")
      || metadataString(agent, "challengeCupTeamId")
      || metadataString(agent, "knowledgeExpansionTeamId"),
    );
    if (!hasTeamMarker) {
      errors.push("team_agent_missing_team_id");
    }
  }
  if (kind === CONVERSATION_INDEX_KIND_USER_CHAT) {
    errors.push("agent_direct_session_cannot_be_user_chat");
  }
  return {
    kind: errors.length > 0 ? CONVERSATION_INDEX_KIND_INVALID : kind,
    errors: [...new Set([...(agent.conversationIndexErrors ?? []), ...errors])],
  };
}

function conversationIndexVisibilityForKind(kind: string) {
  if (kind === CONVERSATION_INDEX_KIND_TEAM_AGENT) {
    return TEAM_PRIVATE_CONVERSATION_INDEX_VISIBILITY;
  }
  if (
    kind === CONVERSATION_INDEX_KIND_USER_CHAT
    || kind === CONVERSATION_INDEX_KIND_PERSONAL_AGENT
    || kind === CONVERSATION_INDEX_KIND_SYSTEM_ENTRY
  ) {
    return USER_VISIBLE_CONVERSATION_INDEX_VISIBILITY;
  }
  return HIDDEN_CONVERSATION_INDEX_VISIBILITY;
}

export function isVisibleConversationAgent(agent: AgentInstance | undefined | null) {
  if (!agent) {
    return false;
  }
  const classification = agentConversationIndexClassification(agent);
  return (
    String(agent.kind ?? "").trim() === "persistent"
    && String(agent.status ?? "").trim().toLowerCase() !== "archived"
    && Boolean(String(agent.directSessionId ?? "").trim())
    && classification.kind !== CONVERSATION_INDEX_KIND_HIDDEN
  );
}

export function agentToConversationSummary(agent: AgentInstance): ConversationSummary {
  const directSessionId = String(agent.directSessionId ?? "").trim();
  const sourceRef = agent.sourceRef ?? makeSourceAuthorityRef("agent", agent.agentId);
  const projectionEdit = makeProjectionEditContract(sourceRef);
  const agentSourceRef = agent.sourceRef ?? makeSourceAuthorityRef("agent", agent.agentId);
  const classification = agentConversationIndexClassification(agent);
  return {
    conversationId: directSessionId || agent.agentId,
    type: "direct_agent",
    title: agent.displayName || agent.agentCode || agent.agentId,
    agentId: agent.agentId,
    agentCode: agent.agentCode,
    agentDisplayName: agent.displayName,
    agentAvatarImagePath: agent.avatarImagePath,
    agentAvatarImageUrl: agent.avatarImageUrl,
    directSessionId,
    roomId: "",
    status: agent.status || "idle",
    summary: "",
    updatedAt: agent.updatedAt || agent.createdAt || "",
    workspacePath: agent.workspacePath || "",
    agentPrimaryMode: agent.primaryMode,
    agentRoleKey: agent.roleKey,
    agentPromptTemplateId: agent.promptTemplateId,
    dialogueModelId: agent.llmBindings?.dialogue?.modelId,
    agentInboxPendingCount: agent.agentInboxPendingCount,
    conversationIndexVisibility: conversationIndexVisibilityForKind(classification.kind),
    conversationIndexKind: classification.kind,
    conversationIndexErrors: classification.errors,
    sourceRef,
    projectionEdit,
    agentSourceRef,
  };
}

function makeSourceAuthorityRef(kind: string, id: string): SourceAuthorityRef {
  const normalizedKind = String(kind || "").trim();
  const normalizedId = String(id || "").trim();
  const owner = sourceOwnerFor(normalizedKind);
  return {
    kind: normalizedKind,
    id: normalizedId,
    owner,
    factAuthority: Boolean(normalizedId && owner !== "unknown"),
    canonicalEditRoute: canonicalEditRouteFor(normalizedKind, normalizedId),
    canonicalMutationApi: canonicalMutationApiFor(normalizedKind, normalizedId),
    projectionCanWrite: false,
    allowedProjectionActions: ALLOWED_PROJECTION_ACTIONS,
    sourceAuthorityVersion: SOURCE_AUTHORITY_VERSION,
  };
}

function makeProjectionEditContract(sourceRef: SourceAuthorityRef): ProjectionEditContract {
  return {
    canWrite: false,
    mode: "deep_link_to_source",
    reason: "projection_read_model",
    sourceOwner: sourceRef.owner,
    canonicalEditRoute: sourceRef.canonicalEditRoute,
    canonicalMutationApi: sourceRef.canonicalMutationApi,
    sourceAuthorityVersion: sourceRef.sourceAuthorityVersion,
  };
}

function sourceOwnerFor(kind: string) {
  if (kind === "agent") {
    return "AgentDirectory";
  }
  if (kind === "session" || kind === "conversation") {
    return "ConversationLedger";
  }
  if (kind === "room" || kind === "chat_room") {
    return "ChatRoomService";
  }
  if (kind === "task" || kind === "kernel_task") {
    return "TaskLedger";
  }
  return "unknown";
}

function canonicalEditRouteFor(kind: string, id: string) {
  const encodedId = encodeURIComponent(id);
  if (!id) {
    return "";
  }
  if (kind === "agent") {
    return `/agents?agent=${encodedId}&pane=config`;
  }
  if (kind === "session" || kind === "conversation") {
    return `/chat?session=${encodedId}`;
  }
  if (kind === "room" || kind === "chat_room") {
    return `/chat?room=${encodedId}`;
  }
  if (kind === "task" || kind === "kernel_task") {
    return `/kernel?taskId=${encodedId}`;
  }
  return "";
}

function canonicalMutationApiFor(kind: string, id: string) {
  const encodedId = encodeURIComponent(id);
  if (!id) {
    return "";
  }
  if (kind === "agent") {
    return `/api/agents/${encodedId}`;
  }
  if (kind === "session" || kind === "conversation") {
    return `/api/sessions/${encodedId}`;
  }
  if (kind === "room" || kind === "chat_room") {
    return `/api/chat-rooms/${encodedId}`;
  }
  if (kind === "task" || kind === "kernel_task") {
    return `/api/kernel/tasks/${encodedId}`;
  }
  return "";
}

export function isVisibleDirectSession(session: SessionSummary | undefined | null) {
  if (!session) {
    return false;
  }
  if (session.agentMissing) {
    return false;
  }
  if (!String(session.agentId ?? "").trim()) {
    return true;
  }
  return true;
}

export function rootSessionIdFor(session: SessionSummary | undefined | null) {
  if (!session) {
    return "";
  }
  if (isChildSession(session)) {
    return String(session.rootSessionId || session.parentSessionId || "").trim();
  }
  return String(session.rootSessionId || session.id || "").trim();
}

export function isRepresentedInAgentSessionTabs(session: SessionSummary | undefined | null) {
  return isChildSession(session);
}

export function hasInvalidChildSessionLink(session: SessionSummary | undefined | null) {
  return isChildSession(session) && !rootSessionIdFor(session);
}

export function isVisibleConversation(
  conversation: ConversationSummary,
  sessionsById?: Map<string, SessionSummary>,
) {
  if (conversation.type !== "direct_agent") {
    return true;
  }
  if (String(conversation.conversationIndexKind ?? "").trim() === CONVERSATION_INDEX_KIND_HIDDEN) {
    return false;
  }
  const sessionId = conversation.directSessionId || conversation.conversationId;
  const session = sessionId && sessionsById ? sessionsById.get(sessionId) : undefined;
  if (String(session?.conversationIndexKind ?? "").trim() === CONVERSATION_INDEX_KIND_HIDDEN) {
    return false;
  }
  if (session) {
    return isVisibleDirectSession(session);
  }
  if (conversation.agentMissing) {
    return false;
  }
  if (!String(conversation.agentId ?? "").trim()) {
    return true;
  }
  return true;
}

export function mergeVisibleSessionsIntoConversations(
  conversations: ConversationSummary[] | undefined,
  sessions: SessionSummary[],
): ConversationSummary[] {
  const merged = conversations ? [...conversations] : [];
  const knownSessionIds = new Set(
    merged
      .filter((conversation) => conversation.type === "direct_agent")
      .flatMap((conversation) => [conversation.directSessionId, conversation.conversationId])
      .filter((value): value is string => Boolean(value)),
  );
  const conversationIndexesBySessionId = new Map<string, number>();
  merged.forEach((conversation, index) => {
    if (conversation.type !== "direct_agent") {
      return;
    }
    if (conversation.directSessionId) {
      conversationIndexesBySessionId.set(conversation.directSessionId, index);
    }
    if (conversation.conversationId) {
      conversationIndexesBySessionId.set(conversation.conversationId, index);
    }
  });
  sessions.forEach((session) => {
    const existingIndex = conversationIndexesBySessionId.get(session.id);
    if (existingIndex !== undefined) {
      const conversation = merged[existingIndex];
      const mergedSession = {
        ...session,
        agentAvatarImagePath: session.agentAvatarImagePath || conversation.agentAvatarImagePath,
        agentAvatarImageUrl: session.agentAvatarImageUrl || conversation.agentAvatarImageUrl,
      };
      merged[existingIndex] = {
        ...conversation,
        ...sessionToConversationSummary(mergedSession),
      };
      return;
    }
    if (knownSessionIds.has(session.id)) {
      return;
    }
    merged.push(sessionToConversationSummary(session));
    knownSessionIds.add(session.id);
  });
  return merged.sort((left, right) =>
    String(right.updatedAt || "").localeCompare(String(left.updatedAt || "")),
  );
}

export function mergeVisibleAgentsIntoConversations(
  conversations: ConversationSummary[],
  agents: AgentInstance[] | undefined,
): ConversationSummary[] {
  const merged = [...conversations];
  const knownSessionIds = new Set(
    merged
      .filter((conversation) => conversation.type === "direct_agent")
      .flatMap((conversation) => [conversation.directSessionId, conversation.conversationId])
      .filter((value): value is string => Boolean(value)),
  );
  const knownAgentIds = new Set(
    merged
      .filter((conversation) => conversation.type === "direct_agent")
      .map((conversation) => String(conversation.agentId ?? "").trim())
      .filter(Boolean),
  );
  (agents ?? []).forEach((agent) => {
    if (!isVisibleConversationAgent(agent)) {
      return;
    }
    const directSessionId = String(agent.directSessionId ?? "").trim();
    const agentId = String(agent.agentId ?? "").trim();
    if (knownSessionIds.has(directSessionId) || (agentId && knownAgentIds.has(agentId))) {
      return;
    }
    merged.push(agentToConversationSummary(agent));
    knownSessionIds.add(directSessionId);
    if (agentId) {
      knownAgentIds.add(agentId);
    }
  });
  return merged.sort((left, right) =>
    String(right.updatedAt || "").localeCompare(String(left.updatedAt || "")),
  );
}

export function classifyConversation(conversation: ConversationSummary): ConversationIndexGroupKey {
  if (conversation.type === "group_room") {
    return "group";
  }
  const kind = normalizeConversationIndexKind(conversation.conversationIndexKind);
  if (kind === CONVERSATION_INDEX_KIND_USER_CHAT) {
    return "user";
  }
  if (kind === CONVERSATION_INDEX_KIND_PERSONAL_AGENT) {
    return "personalAgent";
  }
  if (kind === CONVERSATION_INDEX_KIND_TEAM_AGENT) {
    return "invalid";
  }
  if (kind === CONVERSATION_INDEX_KIND_SYSTEM_ENTRY) {
    return "other";
  }
  return "invalid";
}

export function conversationGroupLabel(groupKey: ConversationIndexGroupKey, lang: "zh" | "en") {
  const labels: Record<ConversationIndexGroupKey, { zh: string; en: string }> = {
    user: { zh: "用户会话", en: "User chats" },
    group: { zh: "群聊", en: "Group chats" },
    personalAgent: { zh: "个人 Agent 会话", en: "Personal agent chats" },
    research: { zh: "科研助手", en: "Research agents" },
    selfEvolution: { zh: "自进化助手", en: "Self-evolution agents" },
    supervisedEvolution: { zh: "监督进化助手", en: "Supervised agents" },
    teams: { zh: "团队", en: "Teams" },
    setupTeams: { zh: "待配置团队", en: "Teams to configure" },
    standaloneGroups: { zh: "未归属群聊", en: "Standalone groups" },
    other: { zh: "其他助手", en: "Other agents" },
    invalid: { zh: "异常会话", en: "Invalid sessions" },
  };
  return labels[groupKey][lang];
}

type BuildConversationIndexModelOptions = {
  agents?: AgentInstance[];
  conversations: ConversationSummary[] | undefined;
  lang: "zh" | "en";
  linkedTeamRoomIds: Set<string>;
  rawSessions: SessionSummary[] | undefined;
  rightIndexSessions: SessionSummary[];
  sessionFilter: string;
  sessionsById: Map<string, SessionSummary>;
  teams: Team[];
};

export function buildConversationIndexModel({
  agents = [],
  conversations,
  lang,
  linkedTeamRoomIds,
  rawSessions,
  rightIndexSessions,
  sessionFilter,
  sessionsById,
  teams,
}: BuildConversationIndexModelOptions) {
  const term = sessionFilter.trim().toLowerCase();
  const rawSessionsById = new Map((rawSessions ?? []).map((session) => [session.id, session]));
  const mergedConversations = mergeVisibleAgentsIntoConversations(
    mergeVisibleSessionsIntoConversations(conversations, rightIndexSessions),
    agents,
  );
  const discussionTeams = normalizeConversationIndexTeams(teams);
  const conversationTeamLookup = buildConversationTeamLookup(discussionTeams);
  const visibleConversations = mergedConversations
    .filter((conversation) => conversation.type !== "group_room")
    .filter((conversation) => {
      const sessionId = conversation.directSessionId || conversation.conversationId;
      const session = sessionId ? sessionsById.get(sessionId) : undefined;
      const rawSession = sessionId ? rawSessionsById.get(sessionId) : undefined;
      if (isRepresentedInAgentSessionTabs(session)) {
        return false;
      }
      if (!isVisibleConversation(conversation, rawSessionsById)) {
        return false;
      }
      if (rawSession && !session) {
        return false;
      }
      return true;
    });
  const filteredConversations = term
    ? visibleConversations.filter((conversation) => {
        const sessionId = conversation.directSessionId || conversation.conversationId;
        const session = sessionsById.get(sessionId);
        const sessionSearchValues = session ? [
          session.title,
          session.taskTitle ?? "",
          session.taskSummary,
          session.status,
          session.currentPhase ?? "",
          session.childStatus ?? "",
          session.resultCard?.summary ?? "",
          session.resultCard?.status ?? "",
          session.parentSessionId ?? "",
          session.rootSessionId ?? "",
        ] : [];
        return [
          conversation.title,
          conversation.summary,
          conversation.status,
          conversation.type,
          conversation.agentCode ?? "",
          conversation.agentDisplayName ?? "",
          conversation.agentPrimaryMode ?? "",
          conversation.agentRoleKey ?? "",
          conversation.agentPromptTemplateId ?? "",
          ...conversationTeamSearchValues(conversationTeamFor(conversation, conversationTeamLookup)),
          ...sessionSearchValues,
        ].some((value) => String(value ?? "").toLowerCase().includes(term));
      })
    : visibleConversations;
  const filteredStandaloneGroupConversations = (conversations ?? [])
    .filter((conversation) => {
      if (conversation.type !== "group_room") {
        return false;
      }
      const roomId = String(conversation.roomId || conversation.conversationId || "").trim();
      return Boolean(roomId) && !linkedTeamRoomIds.has(roomId);
    })
    .filter((conversation) =>
      !term
      || [conversation.title, conversation.summary, conversation.status, conversation.type].some((value) =>
        String(value ?? "").toLowerCase().includes(term),
      ),
    );
  const filteredTeams = term
    ? discussionTeams.filter((team) =>
        [
          team.name,
          team.purpose,
          team.status,
          team.teamKind,
          team.teamCategory,
          team.teamSource,
          team.teamTemplateId,
          team.linkedChatRoom?.title ?? "",
          ...(team.members ?? []).flatMap((member) => [member.agentName, member.agentCode, member.role, member.purpose]),
        ].some((value) => String(value ?? "").toLowerCase().includes(term)),
      )
    : discussionTeams;
  const buckets = new Map<ConversationIndexGroupKey, ConversationSummary[]>(
    CONVERSATION_GROUP_ORDER.map((groupKey) => [groupKey, []]),
  );
  const teamBuckets = new Map<string, { team: ConversationIndexTeam; items: ConversationSummary[] }>();
  filteredConversations.forEach((conversation) => {
    const team = conversationTeamFor(conversation, conversationTeamLookup);
    if (team) {
      const teamId = String(team.teamId ?? "").trim();
      if (teamId) {
        const existing = teamBuckets.get(teamId);
        if (existing) {
          existing.items.push(conversation);
        } else {
          teamBuckets.set(teamId, { team, items: [conversation] });
        }
        return;
      }
    }
    const groupKey = classifyConversation(conversation);
    buckets.get(groupKey)?.push(conversation);
  });
  const leadingGroupKeys: ConversationIndexGroupKey[] = ["user", "group"];
  const trailingGroupKeys = CONVERSATION_GROUP_ORDER.filter((groupKey) => !leadingGroupKeys.includes(groupKey));
  const teamConversationGroups: ConversationIndexGroup[] = [];
  discussionTeams.forEach((team) => {
    const teamId = String(team.teamId ?? "").trim();
    const bucket = teamId ? teamBuckets.get(teamId) : undefined;
    if (!bucket) {
      return;
    }
    teamConversationGroups.push({
      groupKey: conversationTeamGroupKey(teamId),
      label: team.name || teamId,
      items: bucket.items,
      teamId,
      groupKind: "team",
    });
  });
  const groupedConversations = [
    ...leadingGroupKeys
      .map((groupKey) => ({
        groupKey,
        label: conversationGroupLabel(groupKey, lang),
        items: buckets.get(groupKey) ?? [],
        groupKind: "default" as const,
      })),
    ...teamConversationGroups,
    ...trailingGroupKeys
    .map((groupKey) => ({
      groupKey,
      label: conversationGroupLabel(groupKey, lang),
      items: buckets.get(groupKey) ?? [],
      groupKind: "default" as const,
    })),
  ].filter((group) => group.items.length > 0);
  return {
    filteredConversations,
    filteredStandaloneGroupConversations,
    filteredTeams,
    groupedConversations,
    rawSessionsById,
    searchHasTerm: Boolean(term),
  };
}

export function useConversationIndexModel(options: BuildConversationIndexModelOptions) {
  return useMemo(
    () => buildConversationIndexModel(options),
    [
      options.conversations,
      options.agents,
      options.lang,
      options.linkedTeamRoomIds,
      options.rawSessions,
      options.rightIndexSessions,
      options.sessionFilter,
      options.sessionsById,
      options.teams,
    ],
  );
}
