import { fetchJson } from "./client";

export const TEAM_MEMBER_MESSAGE_LIMIT = 40;

export type TeamMemberMessage = {
  messageId: string;
  teamId: string;
  sourceAgentId: string;
  sourceAgentName: string;
  targetAgentId: string;
  targetAgentName: string;
  targetSessionId: string;
  summary: string;
  createdAt: string;
};

export type TeamMemberMessageList = {
  teamId: string;
  teamName: string;
  messages: TeamMemberMessage[];
};

export function teamMemberMessagesUrl(teamId: string, limit = TEAM_MEMBER_MESSAGE_LIMIT) {
  const params = new URLSearchParams({ limit: String(limit) });
  return `/api/teams/${encodeURIComponent(teamId)}/member-messages?${params.toString()}`;
}

export function listTeamMemberMessages(teamId: string, limit = TEAM_MEMBER_MESSAGE_LIMIT, init?: RequestInit) {
  return fetchJson<TeamMemberMessageList>(teamMemberMessagesUrl(teamId, limit), init);
}

export function teamMemberMessageSessionHref(sessionId: string, returnTo?: string, returnLabel?: string) {
  const normalized = String(sessionId || "").trim();
  if (!normalized) {
    return "";
  }
  const params = new URLSearchParams({ session: normalized });
  const nextReturnTo = String(returnTo || "").trim();
  const nextReturnLabel = String(returnLabel || "").trim();
  if (nextReturnTo) {
    params.set("returnTo", nextReturnTo);
  }
  if (nextReturnLabel) {
    params.set("returnLabel", nextReturnLabel);
  }
  return `/chat?${params.toString()}`;
}
