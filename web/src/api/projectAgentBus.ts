import { fetchJson } from "./client";
import type { ProjectAgentBusEvent, ProjectAgentBusTimeline } from "./types";

export const PROJECT_AGENT_BUS_ENDPOINT = "/api/project-agent-bus";
export const PROJECT_AGENT_BUS_TEAM_TIMELINE_LIMIT = 120;

export type SendProjectAgentBusMessageInput = {
  content: string;
  interruptTargets?: boolean;
};

export type SendTeamProjectBusMessageInput = {
  teamId: string;
  content: string;
  interruptMode: string;
};

export type RevokeProjectAgentBusMessageInput = {
  eventId: string;
  reason: string;
};

export function projectAgentBusTimelineUrl(limit?: number) {
  if (!limit) {
    return PROJECT_AGENT_BUS_ENDPOINT;
  }
  return `${PROJECT_AGENT_BUS_ENDPOINT}?limit=${encodeURIComponent(String(limit))}`;
}

export function listProjectAgentBusTimeline(limit?: number) {
  return fetchJson<ProjectAgentBusTimeline>(projectAgentBusTimelineUrl(limit));
}

export function sendProjectAgentBusMessage({ content, interruptTargets = false }: SendProjectAgentBusMessageInput) {
  return fetchJson<ProjectAgentBusEvent>(`${PROJECT_AGENT_BUS_ENDPOINT}/messages`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      content,
      targetScope: "",
      targetAgentIds: [],
      interruptMode: interruptTargets ? "interrupt_targets" : "none",
      wakeTarget: true,
    }),
  });
}

export function sendTeamProjectBusMessage({ teamId, content, interruptMode }: SendTeamProjectBusMessageInput) {
  return fetchJson<ProjectAgentBusEvent>(`/api/teams/${encodeURIComponent(teamId)}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      content,
      interruptMode,
      wakeTarget: true,
    }),
  });
}

export function revokeProjectAgentBusMessage({ eventId, reason }: RevokeProjectAgentBusMessageInput) {
  return fetchJson<ProjectAgentBusEvent>(`${PROJECT_AGENT_BUS_ENDPOINT}/messages/${encodeURIComponent(eventId)}/revoke`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      reason,
      stopTargets: true,
    }),
  });
}

export function isProjectAgentBusEventRevoked(event: ProjectAgentBusEvent) {
  return String(event.status ?? "").trim().toLowerCase() === "revoked";
}

export function projectAgentBusEventsForTeam(
  timeline: ProjectAgentBusTimeline | undefined,
  teamId: string | undefined,
  limit = 6,
) {
  const normalizedTeamId = String(teamId ?? "").trim();
  if (!normalizedTeamId) {
    return [];
  }
  return [...(timeline?.events ?? [])]
    .filter((event) => String(event.metadata?.teamId ?? "").trim() === normalizedTeamId)
    .reverse()
    .slice(0, limit);
}
