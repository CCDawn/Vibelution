import { useCallback, useMemo } from "react";

import type {
  AgentInstance,
  ChatRoomMode,
  ChatRoomParticipant,
  ChatRoomPurpose,
  Team,
} from "../../api/types";
import { participantAgentDisplayInfo } from "../agentDisplay";
import {
  compactAgentRoleLabel,
  formatAgentIdentityLabel,
} from "./chatRoutePresentation";

export interface UseChatGroupRoomViewModelParams {
  archiveVisibleAgents: AgentInstance[];
  chatRoomModes: ChatRoomMode[] | undefined;
  chatRoomPurposes: ChatRoomPurpose[] | undefined;
  activeGroupTeam: Team | null | undefined;
  agentsById: Map<string, AgentInstance>;
  lang: "zh" | "en";
  resolveModelLabel: (modelId: string) => string | undefined;
  avatarImageUrlFrom: (...sources: unknown[]) => string | undefined;
}

export function useChatGroupRoomViewModel({
  archiveVisibleAgents,
  chatRoomModes,
  chatRoomPurposes,
  activeGroupTeam,
  agentsById,
  lang,
  resolveModelLabel,
  avatarImageUrlFrom,
}: UseChatGroupRoomViewModelParams) {
  const groupCandidateAgents = useMemo(() => {
    return archiveVisibleAgents.filter((agent) => {
      return (
        String(agent.kind ?? "").trim() === "persistent"
        && String(agent.status ?? "").trim() !== "archived"
        && String(agent.directSessionId ?? "").trim()
      );
    });
  }, [archiveVisibleAgents]);

  const readyChatRoomModes = useMemo(() => {
    const modes = (chatRoomModes ?? []).filter((mode) => String(mode.status ?? "").trim() === "ready");
    return modes.length ? modes : [{ id: "round_robin", label: "Round robin", status: "ready" }];
  }, [chatRoomModes]);

  const availableChatRoomPurposes = useMemo(() => {
    const purposes = chatRoomPurposes ?? [];
    return purposes.length
      ? purposes
      : [
          { id: "chat", label: "Chat", description: "" },
          { id: "discussion", label: "Discussion", description: "" },
          { id: "meeting", label: "Meeting", description: "" },
          { id: "medical_triage", label: "Medical triage", description: "" },
        ];
  }, [chatRoomPurposes]);

  const activeGroupTeamMemberByAgentId = useMemo(() => {
    return new Map(
      (activeGroupTeam?.members ?? [])
        .map((member) => [String(member.agentId ?? "").trim(), member] as const)
        .filter(([agentId]) => Boolean(agentId)),
    );
  }, [activeGroupTeam?.members]);

  const groupParticipantIdentity = useCallback(
    (
      participant: ChatRoomParticipant | undefined,
      fallback: { agentId?: string; agentCode?: string; title?: string; participantId?: string; agentAvatarImageUrl?: string } = {},
    ) => {
      const agentId = String(participant?.agentId || fallback.agentId || "").trim();
      const participantLike = participant ?? {
        participantId: String(fallback.participantId || agentId || "agent").trim(),
        kind: "session_agent",
        agentId,
        agentCode: String(fallback.agentCode || "").trim(),
        agentAvatarImageUrl: String(fallback.agentAvatarImageUrl || "").trim(),
        sessionId: "",
        title: String(fallback.title || fallback.participantId || agentId || "Agent").trim(),
        enabled: true,
        status: "",
      };
      const participantAgent = agentId ? agentsById.get(agentId) : undefined;
      const display = participantAgentDisplayInfo(participantLike, participantAgent, lang, resolveModelLabel);
      const member = agentId ? activeGroupTeamMemberByAgentId.get(agentId) : undefined;
      const participantTeamRole = String(participant?.teamMemberPurpose || participant?.teamRole || "").trim();
      const role = String(participantTeamRole || member?.purpose || member?.role || display.functionLabel || "").trim();
      const name = String(display.name || fallback.title || fallback.participantId || "Agent").trim();
      const compactRole = compactAgentRoleLabel(role || display.functionLabel);
      return {
        ...display,
        name,
        functionLabel: role || display.functionLabel,
        compactRole,
        avatarImageUrl: avatarImageUrlFrom(participantAgent, participantLike, fallback),
        identityLabel: formatAgentIdentityLabel(name, fallback.participantId || "Agent"),
        fullIdentityLabel: [
          formatAgentIdentityLabel(name, fallback.participantId || "Agent"),
          display.modelLabel,
        ].filter(Boolean).join(" · "),
      };
    },
    [activeGroupTeamMemberByAgentId, agentsById, avatarImageUrlFrom, lang, resolveModelLabel],
  );

  return {
    groupCandidateAgents,
    readyChatRoomModes,
    availableChatRoomPurposes,
    activeGroupTeamMemberByAgentId,
    groupParticipantIdentity,
  };
}
