/**
 * Team workbench shell write mutations (archive/canvas/message/sync/repair/round).
 * EventSource-free; Route remains draft/view orchestration boundary.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { Dispatch, SetStateAction } from "react";

import { fetchJson } from "../../api/client";
import {
  revokeProjectAgentBusMessage,
  sendTeamProjectBusMessage,
} from "../../api/projectAgentBus";
import { queryKeys } from "../../api/queryKeys";
import type { ChatRoomDetail, Team, TeamOrganizationCanvas } from "../../api/types";
import { createChatWorkspaceCache } from "../chatWorkspaceCache";

export type TeamShellChatWorkspaceCache = ReturnType<typeof createChatWorkspaceCache>;

export type UseTeamShellMutationsOptions = {
  selectedTeamId: string;
  setSelectedTeamId: Dispatch<SetStateAction<string>>;
  setSelectedNodeId: Dispatch<SetStateAction<string>>;
  clearTeamSearchParams: () => void;
  setTeamMessage: Dispatch<SetStateAction<string>>;
  setTeamTaskTopic: Dispatch<SetStateAction<string>>;
  chatWorkspaceCache: TeamShellChatWorkspaceCache;
};

export function useTeamShellMutations(options: UseTeamShellMutationsOptions) {
  const queryClient = useQueryClient();
  const { chatWorkspaceCache } = options;

  const archiveTeamMutation = useMutation({
    mutationFn: (teamId: string) =>
      fetchJson<Team>(`/api/teams/${encodeURIComponent(teamId)}`, {
        method: "DELETE",
      }),
    onSuccess: (team, teamId) => {
      options.setSelectedTeamId("");
      options.setSelectedNodeId("");
      options.clearTeamSearchParams();
      void chatWorkspaceCache.afterTeamArchived(teamId, team.linkedChatRoomId || team.linkedChatRoom?.roomId);
    },
  });

  const saveCanvasMutation = useMutation({
    mutationFn: (nextCanvas: TeamOrganizationCanvas) =>
      fetchJson<TeamOrganizationCanvas>(`/api/teams/${encodeURIComponent(nextCanvas.teamId)}/canvas`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(nextCanvas),
      }),
    onSuccess: (canvas, variables) => {
      queryClient.setQueryData(queryKeys.teamCanvas(variables.teamId), canvas);
      void chatWorkspaceCache.afterTeamChanged(variables.teamId);
    },
  });

  const sendTeamMessageMutation = useMutation({
    mutationFn: (payload: { teamId: string; content: string; interruptMode: string }) =>
      sendTeamProjectBusMessage(payload),
    onSuccess: (_payload, variables) => {
      if (variables.teamId === options.selectedTeamId) {
        options.setTeamMessage("");
      }
      void chatWorkspaceCache.afterTeamChanged(variables.teamId);
    },
  });

  const revokeTeamMessageMutation = useMutation({
    mutationFn: (payload: { teamId: string; eventId: string }) =>
      revokeProjectAgentBusMessage({
        eventId: payload.eventId,
        reason: "Revoked from Agent Center team broadcast history.",
      }),
    onSuccess: (_payload, variables) => {
      void chatWorkspaceCache.afterTeamChanged(variables.teamId);
    },
  });

  const syncTeamChatRoomMutation = useMutation({
    mutationFn: (teamId: string) =>
      fetchJson<Team>(`/api/teams/${encodeURIComponent(teamId)}/chat-room/sync`, {
        method: "POST",
      }),
    onSuccess: (team) => {
      queryClient.setQueryData(queryKeys.team(team.teamId, "light"), team);
      queryClient.setQueryData(queryKeys.team(team.teamId, "full"), team);
      if (team.linkedChatRoom?.roomId) {
        void chatWorkspaceCache.afterTeamRoomMembershipChanged(team.teamId, team.linkedChatRoom.roomId);
      } else {
        void chatWorkspaceCache.afterTeamChanged(team.teamId);
      }
    },
  });

  const repairChallengeCupTeamAgentsMutation = useMutation({
    mutationFn: (teamId: string) =>
      fetchJson<{ team: Team }>(`/api/teams/${encodeURIComponent(teamId)}/challenge-cup-agents/repair`, {
        method: "POST",
      }),
    onSuccess: (payload, teamId) => {
      if (payload.team) {
        queryClient.setQueryData(queryKeys.team(payload.team.teamId, "light"), payload.team);
        queryClient.setQueryData(queryKeys.team(payload.team.teamId, "full"), payload.team);
      }
      void chatWorkspaceCache.afterTeamChanged(payload.team?.teamId || teamId);
      void chatWorkspaceCache.afterAgentWorkspaceChanged();
    },
  });

  const repairKnowledgeExpansionTeamAgentsMutation = useMutation({
    mutationFn: (teamId: string) =>
      fetchJson<{ team: Team }>(`/api/teams/${encodeURIComponent(teamId)}/knowledge-expansion-agents/repair`, {
        method: "POST",
      }),
    onSuccess: (payload, teamId) => {
      if (payload.team) {
        queryClient.setQueryData(queryKeys.team(payload.team.teamId, "light"), payload.team);
        queryClient.setQueryData(queryKeys.team(payload.team.teamId, "full"), payload.team);
      }
      void chatWorkspaceCache.afterTeamChanged(payload.team?.teamId || teamId);
      void chatWorkspaceCache.afterAgentWorkspaceChanged();
    },
  });

  const startTeamRoundMutation = useMutation({
    mutationFn: (payload: { roomId: string; teamId: string; topic: string; mode: string; purpose: string }) =>
      fetchJson<ChatRoomDetail>(`/api/chat-rooms/${payload.roomId}/rounds`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          topic: payload.topic,
          mode: payload.mode,
          purpose: payload.purpose,
          config: {
            source: "team_workspace",
            teamId: payload.teamId,
          },
        }),
      }),
    onSuccess: (room, variables) => {
      options.setTeamTaskTopic("");
      queryClient.setQueryData(queryKeys.chatRoom(room.roomId), room);
      void chatWorkspaceCache.afterTeamRoomMembershipChanged(variables.teamId, room.roomId);
    },
  });

  return {
    archiveTeamMutation,
    saveCanvasMutation,
    sendTeamMessageMutation,
    revokeTeamMessageMutation,
    syncTeamChatRoomMutation,
    repairChallengeCupTeamAgentsMutation,
    repairKnowledgeExpansionTeamAgentsMutation,
    startTeamRoundMutation,
  };
}
