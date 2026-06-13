import { useMemo } from "react";

import type { ConversationSummary, SessionSummary, Team } from "../api/types";
import { isChildSession, sessionListTitle } from "./DirectSessionIndexItem";

export type ConversationIndexGroupKey =
  | "user"
  | "group"
  | "research"
  | "selfEvolution"
  | "supervisedEvolution"
  | "teams"
  | "standaloneGroups"
  | "other";

export type ConversationIndexGroup = {
  groupKey: ConversationIndexGroupKey;
  label: string;
  items: ConversationSummary[];
};

export const DEFAULT_COLLAPSED_CONVERSATION_GROUPS: Record<ConversationIndexGroupKey, boolean> = {
  user: false,
  group: false,
  research: true,
  selfEvolution: true,
  supervisedEvolution: true,
  teams: false,
  standaloneGroups: true,
  other: true,
};

export const CONVERSATION_GROUP_ORDER: ConversationIndexGroupKey[] = [
  "user",
  "group",
  "research",
  "selfEvolution",
  "supervisedEvolution",
  "other",
];

const NON_DISCUSSION_TEAM_IDS = new Set(["self-evolution-team", "supervised-evolution-team"]);
const NON_DISCUSSION_TEAM_KINDS = new Set(["self_evolution", "supervised_evolution"]);
const NON_DISCUSSION_TEAM_SOURCES = new Set(["self_evolution", "supervised_evolution"]);

export function isDiscussionTeam(team: Team | undefined | null) {
  if (!team) {
    return false;
  }
  const teamId = String(team.teamId ?? "").trim();
  const teamKind = String(team.teamKind ?? "").trim();
  const teamSource = String(team.teamSource ?? "").trim();
  return !(
    NON_DISCUSSION_TEAM_IDS.has(teamId)
    || NON_DISCUSSION_TEAM_KINDS.has(teamKind)
    || NON_DISCUSSION_TEAM_SOURCES.has(teamSource)
  );
}

export function sessionToConversationSummary(session: SessionSummary): ConversationSummary {
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
  };
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
  const sessionId = conversation.directSessionId || conversation.conversationId;
  const session = sessionId && sessionsById ? sessionsById.get(sessionId) : undefined;
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
  sessions.forEach((session) => {
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

export function classifyConversation(conversation: ConversationSummary): ConversationIndexGroupKey {
  if (conversation.type === "group_room") {
    return "group";
  }
  const primaryMode = String(conversation.agentPrimaryMode ?? "").trim().toLowerCase();
  const roleKey = String(conversation.agentRoleKey ?? "").trim().toLowerCase();
  const promptTemplateId = String(conversation.agentPromptTemplateId ?? "").trim().toLowerCase();
  const title = String(conversation.title ?? "").trim().toLowerCase();
  const combined = `${primaryMode} ${roleKey} ${promptTemplateId} ${title}`;
  if (
    primaryMode === "research"
    || roleKey.startsWith("research_")
    || promptTemplateId.startsWith("prompt-research-")
    || combined.includes("research")
    || combined.includes("广撒网 agent")
    || combined.includes("定向深搜 agent")
    || combined.includes("证据审查 agent")
    || combined.includes("主题生成 agent")
    || combined.includes("主题卡 agent")
  ) {
    return "research";
  }
  if (combined.includes("self_evolution") || combined.includes("自进化")) {
    return "selfEvolution";
  }
  if (combined.includes("supervised") || combined.includes("监督进化")) {
    return "supervisedEvolution";
  }
  if (title.includes("agent")) {
    return "other";
  }
  return "user";
}

export function conversationGroupLabel(groupKey: ConversationIndexGroupKey, lang: "zh" | "en") {
  const labels: Record<ConversationIndexGroupKey, { zh: string; en: string }> = {
    user: { zh: "用户会话", en: "User chats" },
    group: { zh: "群聊", en: "Group chats" },
    research: { zh: "科研助手", en: "Research agents" },
    selfEvolution: { zh: "自进化助手", en: "Self-evolution agents" },
    supervisedEvolution: { zh: "监督进化助手", en: "Supervised agents" },
    teams: { zh: "团队", en: "Teams" },
    standaloneGroups: { zh: "未归属群聊", en: "Standalone groups" },
    other: { zh: "其他助手", en: "Other agents" },
  };
  return labels[groupKey][lang];
}

type BuildConversationIndexModelOptions = {
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
  const mergedConversations = mergeVisibleSessionsIntoConversations(conversations, rightIndexSessions);
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
  const discussionTeams = teams.filter(isDiscussionTeam);
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
  filteredConversations.forEach((conversation) => {
    const groupKey = classifyConversation(conversation);
    buckets.get(groupKey)?.push(conversation);
  });
  const groupedConversations = CONVERSATION_GROUP_ORDER
    .map((groupKey) => ({
      groupKey,
      label: conversationGroupLabel(groupKey, lang),
      items: buckets.get(groupKey) ?? [],
    }))
    .filter((group) => group.items.length > 0);
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
